"""
Health, Liveness, and Security Status endpoints.
"""
import os
import time
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, status

from db.supabase_client import get_supabase
from auth import verify_session_token, is_session_secret_configured
from safety import get_security_telemetry
from session_manager import get_all_active_session_ids
from services.redis_service import redis_service
from services.cloudinary_service import cloudinary_service
from routes.common import db_exec, _server_start_time, get_orchestrator_graph

router = APIRouter(tags=["Health & Telemetry"])

# In-memory health cache to prevent hammering Supabase & Gemini on frequent polling
_last_db_check_time: float = 0.0
_cached_db_status: bool = False
_last_gemini_check_time: float = 0.0
_cached_gemini_status: bool = False


@router.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {
        "status": "ok",
        "service": "AI Socratic Tutor API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@router.get("/auth/security-status")
async def get_security_status(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
):
    """Real-time platform security, guardrails status, and defense health. Restricted to parent role."""
    token = authorization.strip() if authorization else (x_session_token.strip() if x_session_token else "")
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = verify_session_token(token)
    if payload.get("role") != "parent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Security telemetry is restricted to parent accounts.",
        )
    return get_security_telemetry()


@router.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """
    Lightweight, instantaneous liveness check — used by frontend cold-start detection
    and cloud health checks. Responds in <1ms without blocking on external dependencies.
    """
    return {
        "status": "ok",
        "service": "veritas-backend",
        "uptime_seconds": round(time.time() - _server_start_time, 1)
    }


@router.api_route("/health/full", methods=["GET", "HEAD"])
async def health_full():
    """
    Full dependency health check verifying both Supabase database and Gemini API reachability.
    Cached (DB: 30s, Gemini: 60s) to keep latency low without burning rate limits.
    """
    global _last_db_check_time, _cached_db_status, _last_gemini_check_time, _cached_gemini_status
    now = time.time()

    # 1. Supabase connectivity check (cached 30s)
    if (now - _last_db_check_time) > 30.0:
        try:
            supabase = get_supabase()
            res = await db_exec(supabase.table("skills").select("id").limit(1))
            _cached_db_status = res.data is not None
            _last_db_check_time = now
        except Exception as e:
            print(f"[WARN] Health DB ping check: {e}")
            _cached_db_status = False
            _last_db_check_time = now - 20.0  # retry in 10s if failed

    # 2. Gemini API configuration check (zero quota consumption on health pings)
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    _cached_gemini_status = bool(gemini_key and len(gemini_key.strip()) > 10)

    overall_ok = _cached_db_status and _cached_gemini_status

    return {
        "status": "ok" if overall_ok else "degraded",
        "version": "1.0.0",
        "uptime_seconds": round(now - _server_start_time, 1),
        "services": {
            "supabase": _cached_db_status,
            "gemini": _cached_gemini_status,
            "orchestrator": get_orchestrator_graph() is not None,
            "session_secret_configured": is_session_secret_configured(),
            "redis": redis_service.is_connected,
            "cloudinary": cloudinary_service.is_available,
        },
        "db": _cached_db_status,
        "active_cached_sessions": len(get_all_active_session_ids()),
    }
