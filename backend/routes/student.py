"""Student and user domain routes.

Provides endpoints for:
- Student mastery profile retrieval
- LLM session summary generation for dashboard
- User avatar upload with Cloudinary CDN fallback
- TTS voice proxy with ElevenLabs and browser synthesis fallback
- Student data purge (privacy / cleanup)
"""

import asyncio
import hashlib
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
import httpx
from pydantic import BaseModel, Field

from agents.content_agent import generate_session_summary
from auth import verify_session_token, verify_student_access
from bkt.tracker import get_all_skills
from session_manager import clear_student_misconceptions, evict_student_sessions
from db.supabase_client import get_supabase
from rate_limiter import limiter
from routes.common import db_exec, _SESSION_SUMMARY_CACHE
from routes.games import _remove_student_game_records
from services.cloudinary_service import cloudinary_service

logger = logging.getLogger("veritas.student")

router = APIRouter(tags=["student"])


class AvatarUploadRequest(BaseModel):
    image: str = Field(min_length=1, max_length=8 * 1024 * 1024)
    user_id: Optional[str] = Field(default="user", max_length=128)


# ElevenLabs quota exhaustion state and audio bytes cache to save credits
_elevenlabs_exhausted_until: float = 0.0
_TTS_CACHE: dict[str, bytes] = {}


@router.get("/student/{student_id}/mastery")
async def get_mastery(
    student_id: str,
    auth_payload: dict = Depends(verify_student_access),
):
    """Get the full mastery state for a student (protected by scoped session token)."""
    supabase = get_supabase()
    result = await db_exec(
        supabase.table("student_skill_mastery")
        .select("*, skills(name, cc_standard, sequence_order)")
        .eq("student_id", student_id)
    )
    skills = get_all_skills()
    return {"student_id": student_id, "mastery": result.data, "all_skills": skills}


@router.get("/student/{student_id}/summary")
async def get_summary(
    student_id: str,
    session_id: str,
    auth_payload: dict = Depends(verify_student_access),
):
    """Generate an LLM session summary for teacher/parent dashboard (protected by scoped session token)."""
    supabase = get_supabase()

    session_owner = await db_exec(
        supabase.table("sessions")
        .select("id")
        .eq("id", session_id)
        .eq("student_id", student_id)
        .limit(1)
    )
    if not session_owner.data:
        raise HTTPException(status_code=404, detail="Session not found for this student")

    events = await db_exec(
        supabase.table("session_events")
        .select("*")
        .eq("session_id", session_id)
        .eq("student_id", student_id)
        .order("created_at")
    )

    # Skip LLM call if no events yet — student hasn't attempted any problem
    if not events.data:
        return {
            "summary": f"{student_id}'s session is just getting started! No problems have been attempted yet.",
            "events": [],
        }

    # Return cached summary if already generated for this session to save LLM quota
    if session_id in _SESSION_SUMMARY_CACHE:
        return {"summary": _SESSION_SUMMARY_CACHE[session_id], "events": events.data}

    student_row = await db_exec(supabase.table("students").select("*").eq("id", student_id).single())
    mastery_rows = await db_exec(
        supabase.table("student_skill_mastery")
        .select("*")
        .eq("student_id", student_id)
    )
    mastery_state = {r["skill_id"]: r["mastery_prob"] for r in (mastery_rows.data or [])}

    student_name = student_row.data.get("name", "Student") if (student_row and student_row.data) else "Student"
    summary = await asyncio.to_thread(
        generate_session_summary,
        student_name=student_name,
        problems_attempted=events.data or [],
        mastery_state=mastery_state,
        skill_params=get_all_skills(),
    )
    if summary:
        if len(_SESSION_SUMMARY_CACHE) > 100:
            _SESSION_SUMMARY_CACHE.pop(next(iter(_SESSION_SUMMARY_CACHE)))
        _SESSION_SUMMARY_CACHE[session_id] = summary

    return {"summary": summary, "events": events.data}


@router.post("/user/avatar/upload")
async def upload_user_avatar(
    req: AvatarUploadRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
):
    """
    Upload a user profile avatar to Cloudinary CDN with automatic face-detection crop
    and WebP optimization. Falls back seamlessly to returning the input data if CDN is offline.
    """
    if not req.image or not req.image.strip():
        raise HTTPException(status_code=400, detail="Image data cannot be empty.")

    token = authorization.strip() if authorization else (x_session_token.strip() if x_session_token else "")
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = verify_session_token(token)
    caller_id = str(payload.get("sub") or "").strip()
    if not caller_id:
        raise HTTPException(status_code=401, detail="Authenticated subject is required")
    if len(req.image) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Avatar image is too large.")

    clean_user = caller_id
    limiter.enforce_cooldown(
        key=f"avatar_{clean_user}",
        cooldown_seconds=1.0,
        action="avatar upload",
        max_per_minute=20,
    )

    try:
        cdn_url = await asyncio.to_thread(
            cloudinary_service.upload_avatar,
            req.image,
            clean_user,
        )
        if cdn_url:
            return {
                "status": "ok",
                "avatar_url": cdn_url,
                "cdn": True,
            }
    except Exception as e:
        logger.warning(f"Avatar Cloudinary upload failed: {e}")

    return {
        "status": "fallback",
        "avatar_url": req.image,
        "cdn": False,
    }


@router.post("/tts")
async def text_to_speech(
    text: str = Query(..., min_length=1, max_length=2000),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
):
    """Proxy ElevenLabs TTS to protect the API key with seamless fallback to browser synthesis on quota exhaustion."""
    global _elevenlabs_exhausted_until
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty for TTS synthesis.")

    token = authorization.strip() if authorization else (x_session_token.strip() if x_session_token else "")
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = verify_session_token(token)
    caller_id = str(payload.get("sub") or "").strip()
    if not caller_id:
        raise HTTPException(status_code=401, detail="Authenticated subject is required")
    limiter.enforce_cooldown(f"tts_{caller_id}", cooldown_seconds=1.0, action="TTS request", max_per_minute=30)

    # If quota was recently exhausted (within 1 hour), signal frontend to use browser speech synthesis cleanly
    now = time.time()
    if now < _elevenlabs_exhausted_until:
        return Response(
            content=b"",
            status_code=204,
            headers={"X-TTS-Fallback": "browser", "X-TTS-Reason": "quota_cached"}
        )

    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "cgSgspJ2msm6clMCkdW9")

    if not api_key:
        return Response(
            content=b"",
            status_code=204,
            headers={"X-TTS-Fallback": "browser", "X-TTS-Reason": "not_configured"}
        )

    clean_text = text.strip()[:500]
    tts_key = hashlib.md5(f"{voice_id}:{clean_text}".encode("utf-8")).hexdigest()
    if tts_key in _TTS_CACHE:
        return Response(content=_TTS_CACHE[tts_key], media_type="audio/mpeg", headers={"X-TTS-Source": "cache"})

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": clean_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
                timeout=15,
            )

        if resp.status_code == 402 or resp.status_code == 429:
            # ElevenLabs monthly credits exhausted; remember for 1 hour and return 204 fallback cleanly
            _elevenlabs_exhausted_until = now + 3600
            logger.info("ElevenLabs quota exhausted (%d). Switching to browser speech synthesis.", resp.status_code)
            return Response(
                content=b"",
                status_code=204,
                headers={"X-TTS-Fallback": "browser", "X-TTS-Reason": "quota_exceeded"}
            )

        if resp.status_code != 200:
            logger.warning("ElevenLabs TTS status %d: %s", resp.status_code, resp.text[:200])
            return Response(
                content=b"",
                status_code=204,
                headers={"X-TTS-Fallback": "browser", "X-TTS-Reason": f"status_{resp.status_code}"}
            )

        if len(_TTS_CACHE) > 100:
            _TTS_CACHE.pop(next(iter(_TTS_CACHE)))
        _TTS_CACHE[tts_key] = resp.content
        return Response(content=resp.content, media_type="audio/mpeg")
    except Exception as e:
        logger.warning("TTS request error: %s", e)
        return Response(
            content=b"",
            status_code=204,
            headers={"X-TTS-Fallback": "browser", "X-TTS-Reason": "network_error"}
        )


@router.delete("/student/{student_id}/data")
async def delete_student_data(
    student_id: str,
    auth_payload: dict = Depends(verify_student_access),
):
    """Purge a student's practice history, skill mastery profile, session logs, and local game cache (authenticated)."""
    supabase = get_supabase()
    try:
        evict_student_sessions(student_id)
        await db_exec(supabase.table("session_events").delete().eq("student_id", student_id))
        await db_exec(supabase.table("sessions").delete().eq("student_id", student_id))
        await db_exec(supabase.table("student_skill_mastery").delete().eq("student_id", student_id))
        await db_exec(supabase.table("student_game_progress").delete().eq("student_id", student_id))
        # Also remove local games_store.json entry so deleted scores don't reappear from file cache
        _remove_student_game_records(student_id)
        clear_student_misconceptions(student_id)
        await asyncio.to_thread(cloudinary_service.delete_student_assets, student_id)
        return {"status": "ok", "message": "Student practice sessions, events, skill mastery profile, and game records purged."}
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to purge student data: {e}")
