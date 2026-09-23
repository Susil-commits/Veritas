"""Neo AI Platform Assistant domain routes.

Provides endpoints for:
- Default prompt suggestions for visitors / learners
- Socratic platform assistant chat with grounded guardrails, role awareness,
  IP/user rate-limiting, and Redis response caching.
"""

import asyncio
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from agents.neo_agent import run_neo_agent, DEFAULT_SUGGESTIONS
from auth import verify_session_token
from rate_limiter import limiter
from safety import sanitize_input
from services.redis_service import redis_service

logger = logging.getLogger("veritas.neo")

router = APIRouter(tags=["neo"])


class NeoChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)
    visitor_id: str | None = Field(default=None, max_length=128)


@router.get("/neo/suggestions")
async def get_neo_suggestions():
    """Return default prompt suggestions for the Neo AI assistant."""
    return {"suggestions": DEFAULT_SUGGESTIONS}


@router.post("/neo/chat")
async def neo_chat(
    req: NeoChatRequest,
    request: Request,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
    x_visitor_id: str | None = Header(None),
):
    """
    Neo AI Assistant Endpoint — Guardrailed strictly to Veritas platform content.
    Supports authenticated users (Student/Parent) and visitors with sliding rate limits.
    """
    clean_msg = sanitize_input(req.message, max_length=1000)
    if not clean_msg:
        raise HTTPException(status_code=400, detail="Please provide a message for Neo.")

    # 1. Resolve Auth / User Context strictly from verified cryptographic token
    user_context = {"role": "visitor", "authenticated": False}
    token = None
    if authorization:
        parts = authorization.strip().split()
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else (parts[0] if parts else None)
    elif x_session_token:
        token = x_session_token.strip()

    trusted_client_identifier = request.client.host if request.client else "visitor_anon"
    client_identifier = req.visitor_id or x_visitor_id or trusted_client_identifier

    if token:
        try:
            payload = verify_session_token(token)
            role = payload.get("role", "student")
            sub = payload.get("sub")
            name = payload.get("name", "Student" if role == "student" else "Parent")
            user_context = {
                "role": role,
                "authenticated": True,
                "name": name,
            }
            if role == "parent":
                user_context["parent_id"] = sub
                client_identifier = f"parent_{sub}"
            else:
                user_context["student_id"] = sub
                client_identifier = f"student_{sub}"
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid authentication token")

    # 2. Rate Limiting Protection (burst: 1s, window: 30 msgs/min for auth, 20 msgs/min for guests)
    max_rate = 35 if user_context["authenticated"] else 20
    if not user_context["authenticated"]:
        limiter.enforce_auth_rate_limit(
            key=f"neo_ip_{trusted_client_identifier}",
            max_attempts=60,
            window_seconds=60.0,
        )
    limiter.enforce_cooldown(
        key=f"neo_{client_identifier}",
        cooldown_seconds=1.0,
        action="Neo message",
        max_per_minute=max_rate,
    )

    # 2.5 Check Redis response cache for common queries with empty history
    cache_key = None
    if not req.history:
        norm_query = clean_msg.strip().lower()
        if len(norm_query) < 120:
            query_hash = hashlib.md5(norm_query.encode("utf-8")).hexdigest()
            cache_key = f"veritas:neo_query:{user_context['role']}:{query_hash}"
            cached_res = redis_service.get_json(cache_key)
            if cached_res and isinstance(cached_res, dict) and "reply" in cached_res:
                return cached_res

    # 3. Execute Neo Agent with grounded guardrails
    result = await asyncio.to_thread(
        run_neo_agent,
        user_message=clean_msg,
        conversation_history=req.history,
        user_context=user_context,
    )

    response_payload = {
        "status": "ok",
        "reply": result["reply"],
        "guardrailed": result["guardrailed"],
        "guardrail_reason": result.get("guardrail_reason"),
        "suggested_actions": result.get("suggested_actions", DEFAULT_SUGGESTIONS),
        "user_role": user_context["role"],
    }

    # Cache successful answer in Redis with 1-hour TTL
    if cache_key and not result.get("guardrailed"):
        try:
            redis_service.set_json(cache_key, response_payload, ex=3600)
        except Exception:
            pass

    return response_payload
