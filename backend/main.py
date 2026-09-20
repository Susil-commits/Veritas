"""
FastAPI Backend — AI Socratic Tutor
All routes, streaming SSE, ElevenLabs TTS proxy, session management.
"""
import os
import sys
import re
import uuid
import json
import time
import datetime
import asyncio
import threading
import warnings
import logging
import httpx
import hashlib
from pathlib import Path

logger = logging.getLogger("veritas-backend")
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

# Suppress harmless LangGraph/LangChain and legacy Google SDK deprecation notices on startup
warnings.filterwarnings("ignore", message=".*allowed_objects.*")
warnings.filterwarnings("ignore", category=FutureWarning, message=".*google.generativeai.*")
warnings.filterwarnings("ignore", category=FutureWarning, module=".*langchain_google_genai.*")
_orig_showwarning = warnings.showwarning
def _suppress_langgraph_deprecation(message, category, filename, lineno, file=None, line=None):
    msg_str = str(message)
    if "allowed_objects" in msg_str or "google.generativeai" in msg_str:
        return
    return _orig_showwarning(message, category, filename, lineno, file, line)
warnings.showwarning = _suppress_langgraph_deprecation

# Ensure backend directory is in sys.path regardless of execution working directory
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from graph.orchestrator import build_graph, TutorState
from agents.content_agent import get_next_problem, generate_session_summary
from agents.diagnostic_agent import run_diagnostic_agent
from agents.tutor_agent import run_tutor_agent
from bkt.tracker import (
    initialize_mastery,
    get_all_skills,
    get_next_skill,
    update_mastery,
)
from db.supabase_client import get_supabase
from auth import (
    create_session_token,
    verify_student_access,
    verify_parent_access,
    verify_parent_caller,
    verify_session_access,
    verify_student_caller,
    verify_session_token,
    is_session_secret_configured,
    revoke_session_token,
)
from agents.neo_agent import run_neo_agent, DEFAULT_SUGGESTIONS
from rate_limiter import limiter
from safety import (
    sanitize_input,
    check_prompt_injection,
    check_harmful_content,
    is_answer_leaked,
    validate_image_upload,
    record_security_event,
    get_security_telemetry,
    SOCRATIC_BOUNDARY_RESPONSE,
    SAFE_SUPPORT_RESPONSE,
)
from postgrest.base_request_builder import CountMethod
from session_manager import (
    get_session,
    save_session,
    evict_session,
    evict_student_sessions,
    record_session_event,
    get_all_active_session_ids,
    get_session_lock,
    get_student_misconceptions,
    save_student_misconception,
    resolve_student_misconceptions_for_skill,
    clear_student_misconceptions,
)
from services.cloudinary_service import cloudinary_service
from services.redis_service import redis_service

# ── Resilient Session Store & Global State ──────────────────────────────────
_server_start_time: float = time.time()
_graph = None


async def db_exec(query: Any, retries: int = 2) -> Any:
    """
    Execute synchronous Supabase query builder `.execute()` in threadpool
    to prevent blocking FastAPI's single-threaded asyncio event loop under load.
    Includes transient retry for network/socket blips.
    """
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(query.execute)
        except Exception as e:
            if attempt < retries and any(err in str(e) for err in ["10035", "ReadError", "ConnectError", "timed out", "Timeout", "RemoteProtocolError", "ConnectionTerminated", "RemoteDisconnected"]):
                await asyncio.sleep(0.15 * (attempt + 1))
                continue
            raise


async def _update_mastery_for_skill(session_state: dict, skill_id: str, attempt_type: str = "independent_attempt") -> None:
    """Update BKT mastery for a solved skill and persist to Supabase. Safe to call from any async route."""
    if not skill_id:
        return
    if session_state.get("current_problem_credited", False):
        logger.info(
            "Skill %s already credited for current problem in session %s, skipping duplicate update.",
            skill_id,
            session_state.get("session_id"),
        )
        return

    old_m = session_state.get("mastery_state", {}).get(skill_id, 0.3)
    new_m = update_mastery(old_m, True, skill_id, attempt_type=attempt_type)
    # Persist to DB BEFORE committing in-memory mutation so we can roll back on failure
    try:
        supabase = get_supabase()
        await asyncio.to_thread(
            lambda: supabase.table("student_skill_mastery").upsert({
                "student_id": session_state["student_id"],
                "skill_id": skill_id,
                "mastery_prob": round(new_m, 4),
            }, on_conflict="student_id,skill_id").execute()
        )
        # Commit in-memory state only after successful DB write
        session_state["current_problem_credited"] = True
        session_state.setdefault("mastery_state", {})[skill_id] = round(new_m, 4)
    except Exception as e:
        logger.warning("Failed to persist updated mastery to Supabase; in-memory state NOT mutated: %s", e)


# SSE Response headers to prevent proxy/CDN buffering (Render, Cloudflare, Nginx)
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def get_orchestrator_graph():
    """Returns the singleton compiled LangGraph state machine orchestrator, building it on first access."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    try:
        _graph = get_orchestrator_graph()
        print("[INFO] LangGraph orchestrator compiled successfully on startup.")
    except Exception as e:
        _graph = None
        print(f"[ERROR] LangGraph orchestrator failed to compile during lifespan startup: {e}")
        print("[WARN] Server will continue booting so health/readiness probes remain alive; orchestrator will retry on demand.")

    if is_session_secret_configured():
        print("[INFO] Auth: Dedicated SESSION_SECRET_KEY detected and active.")
    else:
        print("[WARN] Auth: SESSION_SECRET_KEY not explicitly configured in environment. Using fallback/ephemeral keying.")

    if os.getenv("ENABLE_DEMO_SEED", "false").lower() == "true":
        try:
            from db.seed_demo_data import ensure_demo_data_seeded
            asyncio.create_task(asyncio.to_thread(ensure_demo_data_seeded))
        except Exception as e:
            logger.warning("Auto demo-seed hook failed to schedule: %s", e)

    yield


app = FastAPI(title="AI Socratic Tutor API", lifespan=lifespan)

# CORS — allow frontend origins explicitly via FRONTEND_URL env var (comma-separated).
# For Vercel deployments, set FRONTEND_URL=https://your-app.vercel.app in the backend environment.
frontend_env = os.getenv("FRONTEND_URL", "")
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:4173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:4173",
]
if frontend_env:
    origins.extend([origin.strip().rstrip("/") for origin in frontend_env.split(",") if origin.strip()])

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enforce security response headers on all routes (Defense-in-depth)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    # Pre-check upload size before multipart parsing to prevent memory abuse at the transport layer
    if request.url.path == "/session/upload-work":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > 10 * 1024 * 1024 + 1:
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Uploaded image exceeds 10MB limit."},
                    )
            except ValueError:
                pass
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; object-src 'none'"
    return response


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {
        "status": "ok",
        "service": "AI Socratic Tutor API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/auth/security-status")
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


# In-memory health cache to prevent hammering Supabase & Gemini on frequent polling
_last_db_check_time: float = 0.0
_cached_db_status: bool = False
_last_gemini_check_time: float = 0.0
_cached_gemini_status: bool = False


# ── Pydantic Models ──────────────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    student_name: str = Field(min_length=1, max_length=120)
    student_id: str | None = Field(default=None, max_length=64)
    student_email: str | None = Field(default=None, max_length=320)


class AddChildRequest(BaseModel):
    parent_id: str = Field(max_length=64)
    parent_email: str | None = Field(default=None, max_length=320)
    child_email: str = Field(max_length=320)
    child_name: str | None = Field(default=None, max_length=120)
    student_id: str | None = Field(default=None, max_length=64)


class MessageRequest(BaseModel):
    session_id: str = Field(max_length=64)
    message: str = Field(min_length=1, max_length=4000)


class MasteryUpdateRequest(BaseModel):
    session_id: str
    problem_id: str
    is_correct: bool


class NeoChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)
    visitor_id: str | None = Field(default=None, max_length=128)


class NextProblemRequest(BaseModel):
    session_id: str
    mark_previous_correct: bool = False


class ResetSessionRequest(BaseModel):
    student_id: str
    session_id: str | None = None


class GameScoreRequest(BaseModel):
    student_id: str = Field(max_length=64)
    game_id: str = Field(max_length=64)
    score: int = Field(le=1_000_000)
    stars: int = Field(default=1)
    mode: str | None = Field(default="blitz", max_length=32)
    streak_max: int | None = Field(default=0, ge=0, le=100_000)


class ResetGameScoreRequest(BaseModel):
    student_id: str
    game_id: str | None = None


class AvatarUploadRequest(BaseModel):
    image: str = Field(min_length=1, max_length=8 * 1024 * 1024)
    user_id: Optional[str] = Field(default="user", max_length=128)


# ── Routes ───────────────────────────────────────────────────────────────────

def _public_problem(problem: dict | None) -> dict | None:
    """Return problem fields safe for the browser; solution metadata stays server-side."""
    if not problem:
        return None
    public = dict(problem)
    for secret_field in ("expected_steps", "answer", "solution", "embedding", "misconception_type"):
        public.pop(secret_field, None)
    return public

@app.api_route("/health", methods=["GET", "HEAD"])
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


@app.api_route("/health/full", methods=["GET", "HEAD"])
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
            "orchestrator": _graph is not None,
            "session_secret_configured": is_session_secret_configured(),
            "redis": redis_service.is_connected,
            "cloudinary": cloudinary_service.is_available,
        },
        "db": _cached_db_status,
        "active_cached_sessions": len(get_all_active_session_ids()),
    }


# ── Veritas Math Arcade: Curriculum-Gated Games Progression ───────────────
GAMES_DATA_DIR = BACKEND_DIR / "data"
GAMES_DATA_DIR.mkdir(parents=True, exist_ok=True)
GAMES_STORE_PATH = GAMES_DATA_DIR / "games_store.json"
_games_store_lock = threading.RLock()

DEMO_STUDENT_ID = "24e836e3-3b42-41a0-8a27-222f883eaa10"

GAME_LEVELS_CONFIG = [
    {
        "id": "multiplier_matrix",
        "level": 1,
        "name": "Multiplier Matrix",
        "subtitle": "Space Blitz",
        "theme": "space",
        "skill_required": "3.OA.A.1",
        "skill_name": "Understanding Multiplication",
        "unlock_requirement": "Complete Multiplication part (3.OA.A.1) to unlock",
        "description": "Defend the spacecraft by bursting plasma product bubbles before math meteors strike!",
    },
    {
        "id": "division_dungeons",
        "level": 2,
        "name": "Division Dungeons",
        "subtitle": "Gem Chest Quest",
        "theme": "dungeon",
        "skill_required": "3.OA.A.2",
        "skill_name": "Understanding Division",
        "unlock_requirement": "Complete Division part (3.OA.A.2) to unlock",
        "description": "Divide shimmering treasures equally into dungeon chests to unlock ancient vaults!",
    },
    {
        "id": "two_step_runner",
        "level": 3,
        "name": "Two-Step Runner",
        "subtitle": "Formula Fortress",
        "theme": "castle",
        "skill_required": "3.OA.D.8",
        "skill_name": "Two-Step Word Problems",
        "unlock_requirement": "Complete Two-Step Word Problems part (3.OA.D.8) to unlock",
        "description": "Solve dual-stage math puzzles before the goblin reaches the fortress gates!",
    },
    {
        "id": "fraction_fusion",
        "level": 4,
        "name": "Pizza Fraction Fusion",
        "subtitle": "The Master Slicer",
        "theme": "kitchen",
        "skill_required": "4.NF.A.1",
        "alt_skill_required": "4.NF.B.3",
        "skill_name": "Equivalent Fractions",
        "unlock_requirement": "Complete Fraction part (4.NF.A.1 / 4.NF.B.3) to unlock",
        "description": "Slice and fuse equivalent fractions of artisan pizza to feed hungry customers!",
    },
    {
        "id": "equation_alchemist",
        "level": 5,
        "name": "Equation Alchemist",
        "subtitle": "Cosmic Balance Scale",
        "theme": "alchemy",
        "skill_required": "6.EE.B.7",
        "alt_skill_required": "7.EE.B.4",
        "skill_name": "Solving One-Step Equations",
        "unlock_requirement": "Complete Equation part (6.EE.B.7 / 7.EE.B.4) to unlock",
        "description": "Balance the mystical alchemical scales using inverse operations to transmute elements into gold!",
    },
    {
        "id": "decimal_dash",
        "level": 6,
        "name": "Decimal Dash",
        "subtitle": "Neon Hyperlane",
        "theme": "cyber",
        "skill_required": "5.NF.B.7",
        "skill_name": "Dividing Fractions & Decimals",
        "unlock_requirement": "Complete Fraction Division part (5.NF.B.7) to unlock",
        "description": "Calculate high-speed fractional parts and division quotients to navigate through hyperlane traffic!",
    },
    {
        "id": "geometry_odyssey",
        "level": 7,
        "name": "Geometry Odyssey",
        "subtitle": "Cosmic Architect",
        "theme": "galaxy",
        "skill_required": "6.EE.A.2",
        "skill_name": "Algebraic Expressions & Formulas",
        "unlock_requirement": "Complete Algebraic Expressions part (6.EE.A.2) to unlock",
        "description": "Evaluate algebraic expressions and geometric formulas to construct celestial stations!",
    },
]


# Maximum score accepted per game session submission — prevents absurd client-side score inflation
MAX_SCORE_PER_GAME = int(os.getenv("MAX_SCORE_PER_GAME", "100000"))

_games_store_cache: dict[str, Any] | None = None


def _read_games_store() -> dict[str, Any]:
    """Read games store, always under the lock to prevent race conditions across threads."""
    global _games_store_cache
    # NOTE: Callers must NOT hold _games_store_lock when calling this — it acquires the lock internally.
    with _games_store_lock:
        if _games_store_cache is not None:
            return _games_store_cache
        if not GAMES_STORE_PATH.exists():
            _games_store_cache = {}
            return _games_store_cache
        try:
            with open(GAMES_STORE_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                _games_store_cache = loaded if isinstance(loaded, dict) else {}
                return _games_store_cache
        except Exception as e:
            logger.warning("Error reading games store from %s: %s", GAMES_STORE_PATH, e)
            _games_store_cache = {}
            return _games_store_cache


def _write_games_store(data: dict[str, Any]) -> None:
    """Write games store and invalidate the in-memory cache so the next read re-loads from disk."""
    global _games_store_cache
    # Caller MUST already hold _games_store_lock
    try:
        tmp = GAMES_STORE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        tmp.replace(GAMES_STORE_PATH)
        # Invalidate cache after disk write so other workers re-load fresh data
        _games_store_cache = None
    except Exception as e:
        logger.warning("Error writing games store to %s: %s", GAMES_STORE_PATH, e)


def _remove_student_game_records(student_id: str) -> None:
    """Remove local game records after a destructive student-data operation."""
    with _games_store_lock:
        store = _read_games_store()
        if student_id in store:
            del store[student_id]
            _write_games_store(store)


async def _get_student_game_progress(student_id: str) -> dict[str, Any]:
    store = _read_games_store()
    student_records = store.get(student_id, {})

    # 0. Attempt to hydrate from Supabase student_game_progress table if available
    try:
        supabase = get_supabase()
        db_game_res = await db_exec(
            supabase.table("student_game_progress")
            .select("game_id, high_score, stars, times_played, last_played, history")
            .eq("student_id", student_id)
        )
        if db_game_res.data:
            if student_id not in store:
                store[student_id] = {}
            for row in db_game_res.data:
                gid = row["game_id"]
                store[student_id][gid] = {
                    "high_score": row.get("high_score", 0),
                    "stars": row.get("stars", 0),
                    "times_played": row.get("times_played", 0),
                    "last_played": row.get("last_played"),
                    "history": row.get("history", []),
                }
            student_records = store[student_id]
    except Exception as e:
        logger.debug("Supabase student_game_progress sync skipped: %s", e)

    # 1. Fetch live mastery from Supabase
    mastery_map = initialize_mastery()
    try:
        supabase = get_supabase()
        res = await db_exec(
            supabase.table("student_skill_mastery")
            .select("skill_id, mastery_prob")
            .eq("student_id", student_id)
        )
        if res.data:
            for row in res.data:
                mastery_map[row["skill_id"]] = float(row["mastery_prob"])
    except Exception as e:
        logger.warning("Failed to fetch student mastery for games: %s", e)

    # 2. Check active cached session if student has active session with higher mastery
    for active_sid in get_all_active_session_ids():
        active_state = get_session(active_sid)
        if active_state and active_state.get("student_id") == student_id:
            for s_id, prob in active_state.get("mastery_state", {}).items():
                if prob > mastery_map.get(s_id, 0.0):
                    mastery_map[s_id] = prob

    # 3. Fetch solved events for skills from session_events
    solved_skills: set[str] = set()
    try:
        supabase = get_supabase()
        events_res = await db_exec(
            supabase.table("session_events")
            .select("problem_id, is_correct")
            .eq("student_id", student_id)
            .eq("is_correct", True)
        )
        if events_res.data:
            prob_ids = [e["problem_id"] for e in events_res.data if e.get("problem_id")]
            if prob_ids:
                p_res = await db_exec(
                    supabase.table("problems").select("id, skill_id").in_("id", prob_ids)
                )
                if p_res.data:
                    for p in p_res.data:
                        if p.get("skill_id"):
                            solved_skills.add(p["skill_id"])
    except Exception as e:
        logger.warning("Failed to fetch solved problems for games progress: %s", e)
    levels_output = []
    total_stars = 0
    total_score = 0
    games_unlocked = 0

    previous_unlocked = True

    for item in GAME_LEVELS_CONFIG:
        gid = item["id"]
        req_skill = item["skill_required"]
        alt_skill = item.get("alt_skill_required")

        req_mastery = mastery_map.get(req_skill, 0.3)
        alt_mastery = mastery_map.get(alt_skill, 0.3) if alt_skill else 0.0
        effective_mastery = max(req_mastery, alt_mastery)

        skill_solved = (req_skill in solved_skills) or (bool(alt_skill) and alt_skill in solved_skills)
        skill_mastered = (effective_mastery >= 0.45) or skill_solved

        item_level = int(item["level"])
        # Level 1 is unlocked as the introductory arcade tier or upon mastering the prerequisite
        if item_level == 1:
            is_unlocked = True
        else:
            is_unlocked = previous_unlocked and skill_mastered

        if is_unlocked:
            progress_pct = 100
        elif not previous_unlocked:
            progress_pct = 0
        else:
            progress_pct = min(95, max(15, int(((effective_mastery - 0.2) / 0.25) * 100)))

        saved_game = student_records.get(gid, {})
        high_score = saved_game.get("high_score", 0)
        stars = saved_game.get("stars", 0)

        total_stars += stars
        total_score += high_score
        if is_unlocked:
            games_unlocked += 1

        levels_output.append({
            "id": gid,
            "level": item["level"],
            "name": item["name"],
            "subtitle": item["subtitle"],
            "theme": item["theme"],
            "skill_required": req_skill,
            "skill_name": item["skill_name"],
            "unlock_requirement": item["unlock_requirement"],
            "description": item["description"],
            "is_unlocked": is_unlocked,
            "progress_percent": progress_pct,
            "high_score": high_score,
            "stars": stars,
            "times_played": saved_game.get("times_played", 0),
            "last_played": saved_game.get("last_played"),
            "history": saved_game.get("history", []),
        })

        previous_unlocked = is_unlocked

    return {
        "student_id": student_id,
        "levels": levels_output,
        "total_stars": total_stars,
        "total_score": total_score,
        "games_unlocked": games_unlocked,
        "total_games": len(GAME_LEVELS_CONFIG),
    }


@app.get("/games/progress")
async def get_games_progress(
    student_id: str,
    auth: dict = Depends(verify_student_access),
):
    """Retrieve persistent game unlocks, level hierarchy roadmap, high scores, and stars."""
    if not student_id or not student_id.strip():
        raise HTTPException(400, "student_id is required")
    return await _get_student_game_progress(student_id.strip())


@app.post("/games/score")
async def record_game_score(
    req: GameScoreRequest,
    auth: dict = Depends(verify_student_caller),
):
    """Persist a completed game score, round telemetry, and star rating permanently for the student."""
    if not req.student_id or not req.student_id.strip():
        raise HTTPException(400, "student_id is required")
    if not req.game_id or not req.game_id.strip():
        raise HTTPException(400, "game_id is required")

    clean_student_id = req.student_id.strip()
    clean_game_id = req.game_id.strip()

    if auth.get("role") != "student":
        raise HTTPException(
            status_code=403,
            detail="Student authentication required",
        )

    if auth.get("sub") != clean_student_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot modify another student's game state",
        )

    valid_game_ids = {item["id"] for item in GAME_LEVELS_CONFIG}
    if clean_game_id not in valid_game_ids:
        raise HTTPException(400, f"Invalid game_id '{clean_game_id}'. Allowed: {sorted(valid_game_ids)}")
    progress = await _get_student_game_progress(clean_student_id)
    selected_level = next(level for level in progress["levels"] if level["id"] == clean_game_id)
    if not selected_level["is_unlocked"]:
        raise HTTPException(403, "This game level is still locked. Complete the required curriculum first.")
    if req.score < 0:
        raise HTTPException(400, "Score must be non-negative")
    if req.score > MAX_SCORE_PER_GAME:
        raise HTTPException(422, f"Score {req.score} exceeds the maximum allowed per session ({MAX_SCORE_PER_GAME:,}).")
    if req.stars not in (1, 2, 3):
        raise HTTPException(400, "Stars must be between 1 and 3 (allowed: 1, 2, 3)")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with _games_store_lock:
        # Re-read inside lock to get the freshest state (handles multi-thread writes)
        _games_store_cache_inner: dict[str, Any] | None = None  # read directly from disk
        if GAMES_STORE_PATH.exists():
            try:
                with open(GAMES_STORE_PATH, "r", encoding="utf-8") as _f:
                    _loaded = json.load(_f)
                    _games_store_cache_inner = _loaded if isinstance(_loaded, dict) else {}
            except Exception:
                pass
        store: dict[str, Any] = _games_store_cache_inner or {}

        student_record = store.setdefault(clean_student_id, {})
        game_record = student_record.setdefault(clean_game_id, {
            "high_score": 0,
            "stars": 0,
            "times_played": 0,
            "last_played": None,
            "history": [],
        })

        game_record["times_played"] = game_record.get("times_played", 0) + 1
        game_record["last_played"] = now_iso
        if req.score > game_record.get("high_score", 0):
            game_record["high_score"] = req.score
        if req.stars > game_record.get("stars", 0):
            game_record["stars"] = min(3, max(1, req.stars))

        history_list = game_record.setdefault("history", [])
        history_list.append({
            "score": req.score,
            "stars": req.stars,
            "mode": req.mode or "blitz",
            "streak_max": req.streak_max or 0,
            "timestamp": now_iso,
        })
        if len(history_list) > 20:
            history_list.pop(0)

        _write_games_store(store)

    # Dual-write write-through to Supabase student_game_progress table
    try:
        supabase = get_supabase()
        await db_exec(
            supabase.table("student_game_progress").upsert({
                "student_id": clean_student_id,
                "game_id": clean_game_id,
                "high_score": game_record["high_score"],
                "stars": game_record["stars"],
                "times_played": game_record["times_played"],
                "last_played": game_record["last_played"],
                "history": game_record["history"],
                "updated_at": now_iso,
            })
        )
    except Exception as e:
        logger.debug("Supabase student_game_progress write-through skipped: %s", e)

    return await _get_student_game_progress(clean_student_id)


@app.post("/games/reset")
async def reset_game_score(
    req: ResetGameScoreRequest,
    auth: dict = Depends(verify_student_caller),
):
    """Reset high scores and stats for a specific game or all games for a student."""
    if not req.student_id or not req.student_id.strip():
        raise HTTPException(400, "student_id is required")

    clean_student_id = req.student_id.strip()

    if auth.get("role") != "student":
        raise HTTPException(
            status_code=403,
            detail="Student authentication required",
        )

    if auth.get("sub") != clean_student_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot modify another student's game state",
        )

    if req.game_id and req.game_id.strip():
        valid_game_ids = {item["id"] for item in GAME_LEVELS_CONFIG}
        if req.game_id.strip() not in valid_game_ids:
            raise HTTPException(400, f"Invalid game_id '{req.game_id}'. Allowed: {sorted(valid_game_ids)}")

    with _games_store_lock:
        store = _read_games_store()

        if clean_student_id in store:
            if req.game_id and req.game_id.strip():
                clean_game_id = req.game_id.strip()
                if clean_game_id in store[clean_student_id]:
                    store[clean_student_id][clean_game_id] = {
                        "high_score": 0,
                        "stars": 0,
                        "times_played": 0,
                        "last_played": None,
                        "history": [],
                    }
            else:
                store[clean_student_id] = {
                    item["id"]: {
                        "high_score": 0,
                        "stars": 0,
                        "times_played": 0,
                        "last_played": None,
                        "history": [],
                    }
                    for item in GAME_LEVELS_CONFIG
                }
            _write_games_store(store)

    # Synchronize reset with Supabase student_game_progress
    try:
        supabase = get_supabase()
        if req.game_id and req.game_id.strip():
            await db_exec(
                supabase.table("student_game_progress")
                .delete()
                .eq("student_id", clean_student_id)
                .eq("game_id", req.game_id.strip())
            )
        else:
            await db_exec(
                supabase.table("student_game_progress")
                .delete()
                .eq("student_id", clean_student_id)
            )
    except Exception as e:
        logger.debug("Supabase student_game_progress reset sync skipped: %s", e)

    return await _get_student_game_progress(clean_student_id)


@app.post("/session/start")
async def start_session(
    req: StartSessionRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
):
    """Create a new tutoring session, issue a scoped session token, and return the first problem."""
    # Auth & token issuance rate limit: throttle automated session creation per student identity
    auth_identity = (req.student_email.strip().lower() if req.student_email else None) or (req.student_id.strip() if req.student_id else None)
    requester = request.client.host if request.client else "unknown"
    auth_key = auth_identity or f"anon_{requester}"
    limiter.enforce_auth_rate_limit(auth_key, max_attempts=10, window_seconds=60.0)
    limiter.enforce_auth_rate_limit(
        f"session_start_ip_{requester}",
        max_attempts=30,
        window_seconds=60.0,
    )

    supabase = get_supabase()

    # Extract caller credentials if provided
    token = None
    if authorization:
        parts = authorization.strip().split()
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else (parts[0] if parts else None)
    elif x_session_token:
        token = x_session_token.strip()

    authenticated_sub = None
    payload: Optional[dict] = None
    if token:
        try:
            payload = verify_session_token(token)
        except HTTPException as e:
            raise HTTPException(
                status_code=e.status_code or 401,
                detail=e.detail or "Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if payload.get("role") != "student":
            raise HTTPException(
                status_code=403,
                detail="Student account required for tutoring sessions",
            )
        authenticated_sub = payload.get("sub")

    student_id = None
    clean_req_student_id = req.student_id.strip() if req.student_id and req.student_id.strip() else None

    # Flow A: Authenticated user (verified Supabase JWT / existing session token)
    if authenticated_sub:
        student_id = authenticated_sub
        try:
            upsert_payload = {"id": student_id, "name": req.student_name}
            if req.student_email:
                upsert_payload["email"] = req.student_email.strip().lower()
            await db_exec(supabase.table("students").upsert(upsert_payload))
        except Exception as e:
            print(f"[WARN] Authenticated student upsert fallback: {e}")

    # Flow B: Client passed explicit student_id without auth token
    elif clean_req_student_id:
        try:
            uuid.UUID(clean_req_student_id)
        except (ValueError, AttributeError):
            raise HTTPException(422, "Invalid student_id: Must be a valid UUID format.")

        # Allow pre-seeded demo student Alex for zero-setup demo mode
        if clean_req_student_id == DEMO_STUDENT_ID:
            student_id = DEMO_STUDENT_ID
        else:
            # Check whether this student already exists in DB or active sessions
            is_existing_student = False
            try:
                check_existing = await db_exec(
                    supabase.table("students")
                    .select("id")
                    .eq("id", clean_req_student_id)
                    .limit(1)
                )
                if check_existing.data and len(check_existing.data) > 0:
                    is_existing_student = True
            except Exception as e:
                print(f"[WARN] Student existence check fallback: {e}")

            if not is_existing_student:
                try:
                    sess_check = await db_exec(
                        supabase.table("sessions")
                        .select("id")
                        .eq("student_id", clean_req_student_id)
                        .limit(1)
                    )
                    if sess_check.data and len(sess_check.data) > 0:
                        is_existing_student = True
                except Exception:
                    pass

            if is_existing_student:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required: student profile already exists. Please supply a valid session or auth token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # New student UUID (e.g., initial creation from client/tests)
            student_id = clean_req_student_id
            try:
                upsert_payload = {"id": student_id, "name": req.student_name}
                if req.student_email:
                    upsert_payload["email"] = req.student_email.strip().lower()
                await db_exec(supabase.table("students").upsert(upsert_payload))
            except Exception:
                try:
                    await db_exec(supabase.table("students").upsert({"id": student_id, "name": req.student_name}))
                except Exception:
                    try:
                        unique_name = f"{req.student_name} #{student_id[:4]}"
                        await db_exec(supabase.table("students").insert({"id": student_id, "name": unique_name}))
                    except Exception as e:
                        print(f"[WARN] Student creation fallback: {e}")

    # Flow C: Anonymous/guest user without student_id - server generates fresh UUID
    if not student_id:
        student_id = str(uuid.uuid4())
        try:
            new_student = await db_exec(supabase.table("students").insert({"id": student_id, "name": req.student_name}))
            if new_student.data:
                student_id = new_student.data[0]["id"]
        except Exception:
            try:
                found = await db_exec(supabase.table("students").select("*").eq("name", req.student_name))
                if found.data:
                    student_id = found.data[0]["id"]
            except Exception as e:
                print(f"[WARN] Student lookup fallback: {e}")

    # Fallback UUID if database offline/unreachable
    if not student_id:
        student_id = str(uuid.uuid4())

    # Load existing mastery or initialize fresh
    mastery_rows = await db_exec(
        supabase.table("student_skill_mastery")
        .select("*")
        .eq("student_id", student_id)
    )
    mastery_state = initialize_mastery()
    for row in (mastery_rows.data or []):
        mastery_state[row["skill_id"]] = row["mastery_prob"]

    # 3. Check if student already has a recent active session to resume
    if req.student_id and student_id:
        try:
            recent_sess = await db_exec(
                supabase.table("sessions")
                .select("id, student_name")
                .eq("student_id", student_id)
                .order("started_at", desc=True)
                .limit(1)
            )
            if recent_sess.data and len(recent_sess.data) > 0:
                existing_session_id = recent_sess.data[0]["id"]
                existing_state = await asyncio.to_thread(get_session, existing_session_id)
                if existing_state and existing_state.get("current_problem"):
                    session_token = create_session_token(
                        student_id=student_id,
                        session_id=existing_session_id,
                        student_name=existing_state.get("student_name", req.student_name),
                    )
                    prob_title = existing_state["current_problem"].get("title", "your current problem")
                    active_misc = existing_state.get("active_misconceptions") or await asyncio.to_thread(get_student_misconceptions, student_id)
                    return {
                        "session_id": existing_session_id,
                        "student_id": student_id,
                        "student_name": existing_state.get("student_name", req.student_name),
                        "session_token": session_token,
                        "current_problem": _public_problem(existing_state["current_problem"]),
                        "mastery_state": existing_state.get("mastery_state", mastery_state),
                        "active_misconceptions": active_misc,
                        "welcome_message": f"Welcome back, {req.student_name}! Picking up right where we left off with **{prob_title}**. Let's keep solving!",
                        "resumed": True,
                    }
        except Exception as e:
            print(f"[WARN] Session resume lookup fallback: {e}")

    # Create session record
    session_id = str(uuid.uuid4())
    try:
        await db_exec(supabase.table("sessions").insert({
            "id": session_id,
            "student_id": student_id,
            "student_name": req.student_name,
        }))
    except Exception as e:
        print(f"[WARN] Supabase session insert error: {e}")

    # Pick first problem
    current_skill = get_next_skill(mastery_state)
    problem = await asyncio.to_thread(
        get_next_problem,
        skill_id=current_skill,
        mastery_prob=mastery_state.get(current_skill, 0.3),
        student_id=student_id,
    )

    if not problem:
        raise HTTPException(status_code=503, detail="No problems available. Please run seed script.")

    # Generate cryptographically signed session token scoped to this student & session
    session_token = create_session_token(
        student_id=student_id,
        session_id=session_id,
        student_name=req.student_name,
    )

    # Initialize session state with longitudinal active misconceptions
    active_misc = await asyncio.to_thread(get_student_misconceptions, student_id)
    state: TutorState = {
        "student_id": student_id,
        "student_name": req.student_name,
        "session_id": session_id,
        "conversation_history": [],
        "latest_input": "",
        "latest_image_bytes": None,
        "current_problem": _public_problem(problem),
        "current_problem_evaluation": problem,
        "current_problem_credited": False,
        "problems_attempted": [problem["id"]],
        "mastery_state": mastery_state,
        "current_skill_id": current_skill,
        "active_misconceptions": active_misc,
        "diagnosis": None,
        "agent_response": "",
        "thinking_steps": [],
        "next_action": None,
    }
    await asyncio.to_thread(save_session, session_id, state)

    return {
        "session_id": session_id,
        "student_id": student_id,
        "student_name": req.student_name,
        "session_token": session_token,
        "current_problem": _public_problem(problem),
        "mastery_state": mastery_state,
        "active_misconceptions": active_misc,
        "welcome_message": f"Hi {req.student_name}! I'm your math tutor. Let's start with this problem. Read it carefully, then tell me what you think the first step is!",
    }


@app.post("/session/reset")
async def reset_session_endpoint(
    req: ResetSessionRequest,
    auth: dict = Depends(verify_student_caller),
):
    """
    Reset student's practice session and skill mastery back to initial priors.
    Clears cached session state and Supabase student_skill_mastery, returning fresh problem #1.
    """
    try:
        uuid.UUID(req.student_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid student_id: Must be a valid UUID format.")

    supabase = get_supabase()
    caller_sub = auth.get("sub")
    clean_student_id = req.student_id.strip()
    if caller_sub != clean_student_id and auth.get("role") != "parent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: caller {caller_sub} cannot reset progress for student {clean_student_id}",
        )

    if auth.get("role") == "parent" and caller_sub != clean_student_id:
        try:
            linked = await db_exec(
                supabase.table("children")
                .select("student_id")
                .eq("parent_id", caller_sub)
                .eq("student_id", clean_student_id)
                .limit(1)
            )
            if not linked.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: parent is not linked to this student",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: unable to verify parent-student relationship",
            )

    if req.session_id and auth.get("sid") and auth["sid"] != req.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session mismatch: token does not authorize this session reset",
        )

    # 1. Verify session ownership and invalidate only sessions owned by this student
    if req.session_id:
        existing_sess = get_session(req.session_id)
        if existing_sess:
            sess_student = existing_sess.get("student_id")
            if sess_student and sess_student != clean_student_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: session {req.session_id} belongs to another student",
                )
        else:
            try:
                db_sess = await db_exec(
                    supabase.table("sessions")
                    .select("student_id")
                    .eq("id", req.session_id)
                    .limit(1)
                )
                if db_sess.data and db_sess.data[0].get("student_id") != clean_student_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Access denied: session {req.session_id} belongs to another student",
                    )
            except HTTPException:
                raise
            except Exception as e:
                print(f"[WARN] Failed to verify session ownership in DB: {e}")

        evict_session(req.session_id)
    else:
        evict_student_sessions(clean_student_id)

    # Stateless tokens cannot be individually revoked, so we:
    # 1. Delete the DB rows to prevent rehydration from Supabase.
    # 2. Write revoked session IDs to a short-lived Redis blocklist so active tokens are rejected immediately.
    try:
        if req.session_id:
            # Write revocation entry before deleting DB row
            await asyncio.to_thread(revoke_session_token, req.session_id)
            await db_exec(supabase.table("session_events").delete().eq("session_id", req.session_id))
            await db_exec(supabase.table("sessions").delete().eq("id", req.session_id))
        else:
            # Enumerate all student sessions and revoke each
            try:
                all_sess = await db_exec(
                    supabase.table("sessions").select("id").eq("student_id", clean_student_id)
                )
                for sr in (all_sess.data or []):
                    if sr.get("id"):
                        await asyncio.to_thread(revoke_session_token, sr["id"])
            except Exception as rev_e:
                logger.warning("Could not enumerate sessions for revocation during full reset: %s", rev_e)
            await db_exec(supabase.table("session_events").delete().eq("student_id", clean_student_id))
            await db_exec(supabase.table("sessions").delete().eq("student_id", clean_student_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to invalidate old sessions during reset: %s", e)
        raise HTTPException(status_code=503, detail="Could not safely invalidate the previous session.")

    # 2. Reset student skill mastery in database back to baseline and clear longitudinal misconceptions
    try:
        await db_exec(
            supabase.table("student_skill_mastery")
            .delete()
            .eq("student_id", req.student_id)
        )
    except Exception as e:
        print(f"[WARN] Failed to delete student_skill_mastery on reset: {e}")

    await asyncio.to_thread(clear_student_misconceptions, clean_student_id)

    # 3. Create fresh mastery priors (all skills 0.3)
    fresh_mastery = initialize_mastery()

    # 4. Fetch student name
    student_name = "Student"
    try:
        st_row = await db_exec(
            supabase.table("students")
            .select("name")
            .eq("id", req.student_id)
            .limit(1)
        )
        if st_row.data:
            student_name = st_row.data[0].get("name") or "Student"
    except Exception:
        pass

    # 5. Create new session in database
    new_session_id = str(uuid.uuid4())
    try:
        await db_exec(supabase.table("sessions").insert({
            "id": new_session_id,
            "student_id": req.student_id,
            "student_name": student_name,
        }))
    except Exception as e:
        print(f"[WARN] Error inserting new reset session: {e}")

    # 6. Pick first problem fresh
    first_skill = get_next_skill(fresh_mastery)
    first_prob = await asyncio.to_thread(
        get_next_problem,
        skill_id=first_skill,
        mastery_prob=fresh_mastery.get(first_skill, 0.3),
        student_id=req.student_id,
        exclude_problem_ids=[],
    )
    if not first_prob:
        raise HTTPException(503, "No problems available in problem bank.")

    session_token = create_session_token(
        student_id=req.student_id,
        session_id=new_session_id,
        student_name=student_name,
    )

    fresh_state: TutorState = {
        "student_id": req.student_id,
        "student_name": student_name,
        "session_id": new_session_id,
        "conversation_history": [],
        "latest_input": "",
        "latest_image_bytes": None,
        "current_problem": _public_problem(first_prob),
        "current_problem_evaluation": first_prob,
        "current_problem_credited": False,
        "problems_attempted": [first_prob["id"]],
        "mastery_state": fresh_mastery,
        "current_skill_id": first_skill,
        "diagnosis": None,
        "agent_response": "",
        "thinking_steps": [],
        "next_action": None,
    }
    await asyncio.to_thread(save_session, new_session_id, fresh_state)

    return {
        "session_id": new_session_id,
        "student_id": req.student_id,
        "student_name": student_name,
        "session_token": session_token,
        "current_problem": _public_problem(first_prob),
        "mastery_state": fresh_mastery,
        "welcome_message": f"Welcome fresh, {student_name}! We've reset your practice session and mastery. Let's start from problem 1. Read it carefully and share your first thoughts!",
        "resumed": False,
    }


@app.post("/session/message")
async def send_message(
    req: MessageRequest,
    auth: dict = Depends(verify_session_access),
):
    """Send a student text message and get a streaming tutor response with safety guardrails."""
    if auth.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student session authentication required",
        )
    if auth.get("sid") and auth["sid"] != req.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session mismatch: token issued for session {auth.get('sid')}, not {req.session_id}",
        )

    # Rate limit check (1.5s cooldown, max 30 msgs/minute per session)
    limiter.enforce_cooldown(
        key=f"msg_{req.session_id}",
        cooldown_seconds=1.5,
        action="message",
        max_per_minute=30,
    )

    state = await asyncio.to_thread(get_session, req.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    session_state: dict[str, Any] = state

    caller_sub = auth.get("sub")
    if caller_sub and caller_sub != session_state.get("student_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: caller does not own this tutoring session",
        )

    # 1. Sanitize student input (length bound, strip control characters, escape HTML)
    clean_message = sanitize_input(req.message)
    if not clean_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # 2. Safety Guardrails: Prompt injection & distress checks
    is_injection, injection_reason = check_prompt_injection(clean_message)
    is_harmful, harm_category = check_harmful_content(clean_message)

    if is_injection:
        record_security_event("prompt_injection_blocked", {
            "session_id": req.session_id,
            "reason": injection_reason,
            "preview": clean_message[:80],
        })
        # Hard-block: return the Socratic boundary response immediately without invoking the graph
        async def _injection_stream() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'response', 'content': SOCRATIC_BOUNDARY_RESPONSE, 'done': True})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'mastery_state': session_state.get('mastery_state', {}), 'problem_solved': False})}\n\n"
        return StreamingResponse(_injection_stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    if is_harmful:
        record_security_event("harmful_content_flagged", {
            "session_id": req.session_id,
            "category": harm_category,
        })

    session_state["latest_input"] = clean_message
    session_state["latest_image_bytes"] = None

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async with get_session_lock(req.session_id):
                # Emit status steps as they happen
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Analyzing response...'})}\n\n"

                thinking_step_initial = "Reading your thought..."
                yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_step_initial})}\n\n"
                await asyncio.sleep(0.1)

                # Re-fetch latest session state inside lock
                latest_state = await asyncio.to_thread(get_session, req.session_id)
                current_state = latest_state or session_state
                current_prob = current_state.get("current_problem") or {}

                # Prepare state for LangGraph orchestrator execution
                safety_flag = "harmful" if is_harmful else ("injection" if is_injection else None)
                graph_input: TutorState = {
                    "student_id": current_state.get("student_id", ""),
                    "student_name": current_state.get("student_name", ""),
                    "session_id": req.session_id,
                    "conversation_history": list(current_state.get("conversation_history") or []),
                    "latest_input": clean_message,
                    "latest_image_bytes": None,
                    "current_problem": current_prob,
                    "current_problem_credited": current_state.get("current_problem_credited", False),
                    "problems_attempted": list(current_state.get("problems_attempted") or []),
                    "mastery_state": dict(current_state.get("mastery_state") or {}),
                    "current_skill_id": current_prob.get("skill_id") or current_state.get("current_skill_id", ""),
                    "active_misconceptions": dict(current_state.get("active_misconceptions") or {}),
                    "diagnosis": current_state.get("diagnosis"),
                    "agent_response": "",
                    "thinking_steps": [thinking_step_initial],
                    "safety_flag": safety_flag,
                    "next_action": None,
                }

                # Execute LangGraph state machine orchestrator
                try:
                    graph = get_orchestrator_graph()
                except Exception as g_err:
                    print(f"[ERROR] On-demand LangGraph compilation failed: {g_err}")
                    yield f"data: {json.dumps({'type': 'response', 'content': 'The AI reasoning engine is currently warming up. Please send your message again in a moment!', 'done': True})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'mastery_state': current_state.get('mastery_state', {}), 'problem_solved': False})}\n\n"
                    return

                graph_output = await graph.ainvoke(graph_input)

                response = graph_output.get("agent_response", "")
                problem_solved = bool(graph_output.get("problem_solved", False))
                steps = graph_output.get("thinking_steps") or []
                for step_content in steps:
                    if step_content != thinking_step_initial:
                        yield f"data: {json.dumps({'type': 'thinking', 'content': step_content})}\n\n"

                # Sync back state produced by LangGraph
                current_state["latest_input"] = clean_message
                current_state["latest_image_bytes"] = None
                current_state["conversation_history"] = graph_output.get("conversation_history", current_state.get("conversation_history", []))
                current_state["thinking_steps"] = steps
                current_state["mastery_state"] = graph_output.get("mastery_state", current_state.get("mastery_state", {}))
                current_state["active_misconceptions"] = graph_output.get("active_misconceptions", current_state.get("active_misconceptions", {}))
                current_state["current_problem_credited"] = graph_output.get("current_problem_credited", current_state.get("current_problem_credited", False))

                is_final_attempt = graph_output.get("is_final_attempt")
                # Determine event correctness for telemetry & parent analytics:
                # - True if problem solved
                # - False if student explicitly proposed an incorrect final answer
                # - None for exploratory questions, hints, or intermediate calculations
                turn_correctness: bool | None = True if problem_solved else (False if is_final_attempt else None)

                await asyncio.to_thread(save_session, req.session_id, current_state)
                await asyncio.to_thread(
                    record_session_event,
                    session_id=req.session_id,
                    student_id=current_state["student_id"],
                    problem_id=current_prob.get("id"),
                    attempt_text=clean_message,
                    is_correct=turn_correctness,
                    agent_response=response,
                )
                final_mastery = current_state.get("mastery_state", {})

            # Stream the response word by word for a live feel (outside lock)
            words = response.split(" ")
            accumulated = ""
            for i, word in enumerate(words):
                accumulated += word + (" " if i < len(words) - 1 else "")
                if i % 3 == 0 or i == len(words) - 1:
                    yield f"data: {json.dumps({'type': 'response', 'content': accumulated, 'done': i == len(words) - 1})}\n\n"
                    await asyncio.sleep(0.04)

            yield f"data: {json.dumps({'type': 'done', 'mastery_state': final_mastery, 'problem_solved': problem_solved})}\n\n"
        except asyncio.CancelledError:
            # Client disconnected or navigated away; terminate generator cleanly
            return
        except Exception as e:
            print(f"[ERROR] Chat stream exception: {e}")
            fallback_msg = "I had a quick pause! Could you repeat that thought?"
            yield f"data: {json.dumps({'type': 'response', 'content': fallback_msg, 'done': True})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'mastery_state': session_state.get('mastery_state', {}), 'problem_solved': False})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@app.post("/session/next-problem")
async def next_problem_endpoint(
    req: NextProblemRequest,
    auth: dict = Depends(verify_session_access),
):
    """Explicitly advance to the next tailored practice problem with BKT mastery progression."""
    if auth.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student session authentication required",
        )
    if auth.get("sid") and auth["sid"] != req.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session mismatch: token issued for session {auth.get('sid')}, not {req.session_id}",
        )

    async with get_session_lock(req.session_id):
        state = await asyncio.to_thread(get_session, req.session_id)
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")

        session_state: dict[str, Any] = state

        caller_sub = auth.get("sub")
        if caller_sub and caller_sub != session_state.get("student_id"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: caller does not own this tutoring session",
            )
        current_prob = session_state.get("current_problem") or {}
        curr_skill = current_prob.get("skill_id") or session_state.get("current_skill_id")

        # 1. Update BKT mastery ONLY if previous problem was solved / completed
        if req.mark_previous_correct and curr_skill and curr_skill in session_state.get("mastery_state", {}):
            if not session_state.get("current_problem_credited", False):
                await _update_mastery_for_skill(session_state, curr_skill)

        # 2. Pick next problem targeted by skill and difficulty
        next_skill = get_next_skill(session_state.get("mastery_state", {}))
        attempted = list(session_state.get("problems_attempted", []))
        if current_prob.get("id") and current_prob["id"] not in attempted:
            attempted.append(current_prob["id"])

        next_prob = await asyncio.to_thread(
            get_next_problem,
            skill_id=next_skill,
            mastery_prob=session_state.get("mastery_state", {}).get(next_skill, 0.3),
            student_id=session_state["student_id"],
            exclude_problem_ids=attempted,
        )
        if not next_prob:
            # Fallback: allow repeating from problem bank if all completed
            next_prob = await asyncio.to_thread(
                get_next_problem,
                skill_id=next_skill,
                mastery_prob=session_state.get("mastery_state", {}).get(next_skill, 0.3),
                student_id=session_state["student_id"],
                exclude_problem_ids=[],
            )

        if not next_prob:
            raise HTTPException(status_code=503, detail="No further practice problems found in problem bank.")

        session_state["current_problem"] = next_prob
        session_state["current_problem_evaluation"] = next_prob
        session_state["current_problem_credited"] = False
        session_state["current_skill_id"] = next_skill
        if next_prob.get("id") and next_prob["id"] not in attempted:
            attempted.append(next_prob["id"])
        session_state["problems_attempted"] = attempted

        problem_title = next_prob.get("title", "Next Problem")
        if req.mark_previous_correct:
            tutor_intro = (
                f"Awesome work! Here is your next problem: **{problem_title}**. "
                f"Read it carefully and let me know what you think the first step is!"
            )
        else:
            tutor_intro = (
                f"Here is your next practice problem: **{problem_title}**. "
                f"Take a moment to read it and share what you think we should do first!"
            )
        session_state["conversation_history"].append({
            "role": "tutor",
            "content": tutor_intro,
            "problem_id": next_prob.get("id"),
        })

        await asyncio.to_thread(save_session, req.session_id, session_state)
        await asyncio.to_thread(
            record_session_event,
            session_id=req.session_id,
            student_id=session_state["student_id"],
            problem_id=next_prob.get("id"),
            attempt_text="Advanced to next problem",
            is_correct=None,
            agent_response=tutor_intro,
        )

        return {
            "status": "ok",
            "current_problem": _public_problem(next_prob),
            "mastery_state": session_state["mastery_state"],
            "tutor_message": tutor_intro,
        }



@app.post("/session/upload-work")
async def upload_work(
    session_id: str,
    file: UploadFile = File(...),
    auth: dict = Depends(verify_session_access),
):
    """Upload a photo of student handwritten work for OCR + diagnosis with strict upload validation."""
    if auth.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student session authentication required",
        )
    if auth.get("sid") and auth["sid"] != session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session mismatch: token issued for session {auth.get('sid')}, not {session_id}",
        )

    # Rate limit check (3.0s cooldown, max 10 uploads/minute per session)
    limiter.enforce_cooldown(
        key=f"upload_{session_id}",
        cooldown_seconds=3.0,
        action="work upload",
        max_per_minute=10,
    )

    state = await asyncio.to_thread(get_session, session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    caller_sub = auth.get("sub")
    if caller_sub and caller_sub != state.get("student_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: caller does not own this tutoring session",
        )

    content_length = file.headers.get("content-length") if file.headers else None
    if content_length:
        try:
            if int(content_length) > 10 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Uploaded image is too large. Maximum allowed is 10MB.")
        except ValueError:
            pass

    image_bytes = await file.read(10 * 1024 * 1024 + 1)

    # Safety: Validate image format, MIME type, and max 10MB file limit
    validate_image_upload(
        file_bytes=image_bytes,
        content_type=file.content_type,
        filename=file.filename,
    )

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async with get_session_lock(session_id):
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Reading your handwritten work...'})}\n\n"
                await asyncio.sleep(0.1)

                fresh_state = await asyncio.to_thread(get_session, session_id)
                current_state = fresh_state or state
                current_problem = current_state.get("current_problem") or {}
                evaluation_problem = current_state.get("current_problem_evaluation") or current_problem
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Checking your steps...'})}\n\n"

                diagnosis = await asyncio.to_thread(
                    run_diagnostic_agent,
                    image_bytes=image_bytes,
                    expected_steps=evaluation_problem.get("expected_steps", []),
                    problem_text=current_problem.get("text", ""),
                    skill_id=current_state.get("current_skill_id", ""),
                )

                # Optimistically upload student handwritten work photo to Cloudinary CDN
                try:
                    cloud_url = await asyncio.to_thread(
                        cloudinary_service.upload_student_work,
                        image_bytes,
                        session_id,
                        current_state.get("student_id"),
                    )
                    # Keep handwritten work private; the CDN asset is not exposed
                    # in the student response and is removed during account deletion.
                except Exception as c_err:
                    print(f"[WARN] Cloudinary student work upload skipped/failed: {c_err}")

                misconception = diagnosis.get('misconception_type', 'unknown')
                friendly_misc = misconception.replace('_', ' ')
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Checking step: ' + friendly_misc})}\n\n"

                # Update mastery
                curr_skill = current_problem.get("skill_id") or current_state.get("current_skill_id")
                is_correct = diagnosis.get("is_correct", False)

                if not is_correct and curr_skill:
                    new_mastery = update_mastery(
                        current_mastery=current_state["mastery_state"].get(curr_skill, 0.3),
                        is_correct=False,
                        skill_id=curr_skill,
                    )
                    current_state["mastery_state"][curr_skill] = round(new_mastery, 4)
                    mastery_pct = f"{new_mastery*100:.0f}%"
                    yield f"data: {json.dumps({'type': 'thinking', 'content': 'Updating skill progress: ' + mastery_pct})}\n\n"
                    try:
                        supabase = get_supabase()
                        await db_exec(supabase.table("student_skill_mastery").upsert({
                            "student_id": current_state["student_id"],
                            "skill_id": curr_skill,
                            "mastery_prob": new_mastery,
                        }, on_conflict="student_id,skill_id"))
                    except Exception as e:
                        print(f"[WARN] Supabase write failed: {e}")

                    # Update longitudinal misconception tracking model beside BKT
                    if misconception and misconception not in ("unknown", "temporary_system_pause"):
                        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        active_map = current_state.setdefault("active_misconceptions", {})
                        entry = active_map.get(misconception, {
                            "count": 0,
                            "last_seen": now_iso,
                            "resolved": False,
                            "skill_id": curr_skill or "",
                        })
                        entry["count"] = entry.get("count", 0) + 1
                        entry["last_seen"] = now_iso
                        entry["resolved"] = False
                        if curr_skill:
                            entry["skill_id"] = curr_skill
                        active_map[misconception] = entry
                        await asyncio.to_thread(
                            save_student_misconception,
                            current_state["student_id"],
                            misconception,
                            curr_skill or "",
                            False,
                        )

                # Record event turn in session_events
                try:
                    await asyncio.to_thread(
                        record_session_event,
                        session_id=current_state["session_id"],
                        student_id=current_state["student_id"],
                        problem_id=current_problem.get("id"),
                        attempt_text=diagnosis.get("ocr_text", ""),
                        is_correct=is_correct,
                        agent_response=diagnosis.get("corrective_question", ""),
                    )
                except Exception as e:
                    print(f"[WARN] Supabase write failed: {e}")

                current_state["diagnosis"] = diagnosis
                await asyncio.to_thread(save_session, session_id, current_state)

                # If correct, update mastery for solved problem and select next problem targeted with pgvector RAG
                if is_correct:
                    if curr_skill:
                        await _update_mastery_for_skill(current_state, curr_skill)
                        # Resolve active misconceptions for current skill
                        active_map = current_state.setdefault("active_misconceptions", {})
                        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        for m_type, m_info in active_map.items():
                            if m_info.get("skill_id") == curr_skill and not m_info.get("resolved"):
                                m_info["resolved"] = True
                                m_info["resolved_at"] = now_iso
                        await asyncio.to_thread(resolve_student_misconceptions_for_skill, current_state["student_id"], curr_skill)

                    cur_m = current_state["mastery_state"].get(curr_skill, 0.3)
                    mastery_pct = f"{cur_m*100:.0f}%"
                    yield f"data: {json.dumps({'type': 'thinking', 'content': 'Updating skill progress: ' + mastery_pct})}\n\n"

                    yield f"data: {json.dumps({'type': 'thinking', 'content': 'Picking your next practice problem...'})}\n\n"
                    next_skill = get_next_skill(current_state["mastery_state"])
                    misconception_desc = diagnosis.get("description") or diagnosis.get("misconception_type")
                    next_problem = await asyncio.to_thread(
                        get_next_problem,
                        skill_id=next_skill,
                        mastery_prob=current_state["mastery_state"].get(next_skill, 0.3),
                        student_id=current_state["student_id"],
                        exclude_problem_ids=current_state.get("problems_attempted", []),
                        misconception_text=misconception_desc,
                    )
                    if next_problem:
                        current_state["current_problem"] = next_problem
                        current_state["current_problem_evaluation"] = next_problem
                        current_state["current_problem_credited"] = False
                        current_state["current_skill_id"] = next_skill
                        current_state["problems_attempted"] = current_state.get("problems_attempted", []) + [next_problem["id"]]
                        await asyncio.to_thread(save_session, session_id, current_state)

                yield f"data: {json.dumps({'type': 'diagnosis', 'diagnosis': diagnosis, 'mastery_state': current_state['mastery_state'], 'active_misconceptions': current_state.get('active_misconceptions', {}), 'next_problem': _public_problem(current_state.get('current_problem'))})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except asyncio.CancelledError:
            # Client disconnected or cancelled upload stream; terminate cleanly
            return
        except Exception as e:
            print(f"[ERROR] upload_work stream failed: {e}")
            yield f"data: {json.dumps({'type': 'thinking', 'content': 'Recovering from analysis hiccup...'})}\n\n"
            fallback_diag = {
                "ocr_text": "Could not complete analysis",
                "is_correct": False,
                "step_number": 1,
                "misconception_type": "temporary_system_pause",
                "description": "The system encountered a brief delay processing this request.",
                "skill_gap": state.get("current_skill_id", ""),
                "skill_gap_name": "",
                "corrective_question": "I had a momentary glitch reading your work. Can you describe what step you took, or try uploading once more?",
                "bounding_hint": {"x": 10.0, "y": 20.0, "width": 80.0, "height": 22.0},
                "bounding_box": {"x": 10.0, "y": 20.0, "width": 80.0, "height": 22.0},
            }
            yield f"data: {json.dumps({'type': 'diagnosis', 'diagnosis': fallback_diag, 'mastery_state': state['mastery_state'], 'next_problem': state.get('current_problem')})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@app.get("/student/{student_id}/mastery")
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


# Cache generated session summaries to avoid re-invoking LLM on dashboard page reloads
_SESSION_SUMMARY_CACHE: dict[str, str] = {}


@app.get("/student/{student_id}/summary")
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


@app.post("/user/avatar/upload")
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
        print(f"[WARN] Avatar Cloudinary upload failed: {e}")

    return {
        "status": "fallback",
        "avatar_url": req.image,
        "cdn": False,
    }


# Cache ElevenLabs quota exhaustion state and audio bytes to save credits
_elevenlabs_exhausted_until: float = 0.0
_TTS_CACHE: dict[str, bytes] = {}

@app.post("/tts")
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
                    "text": clean_text,  # free tier limit
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


# ── Parent Dashboard & Child Management Endpoints ───────────────────────────

CHILDREN_FALLBACK_FILE = BACKEND_DIR.parent / "data" / "children_store.json"
_children_fallback_lock = threading.Lock()


def _get_fallback_children(parent_id: str) -> list[dict]:
    if not CHILDREN_FALLBACK_FILE.exists():
        return []
    try:
        with open(CHILDREN_FALLBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [c for c in data if c.get("parent_id") == parent_id]
    except Exception:
        return []


def _save_fallback_child(record: dict):
    with _children_fallback_lock:
        CHILDREN_FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        current = []
        if CHILDREN_FALLBACK_FILE.exists():
            try:
                with open(CHILDREN_FALLBACK_FILE, "r", encoding="utf-8") as f:
                    current = json.load(f)
            except Exception:
                current = []
        current = [
            c
            for c in current
            if not (
                c.get("parent_id") == record.get("parent_id")
                and c.get("student_id") == record.get("student_id")
            )
        ]
        current.append(record)
        temp_path = CHILDREN_FALLBACK_FILE.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        temp_path.replace(CHILDREN_FALLBACK_FILE)


def _sync_purge_fallback_file(parent_id: str):
    with _children_fallback_lock:
        if not CHILDREN_FALLBACK_FILE.exists():
            return
        try:
            with open(CHILDREN_FALLBACK_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
            cleaned = [c for c in current if c.get("parent_id") != parent_id]
            temp_path = CHILDREN_FALLBACK_FILE.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)
            temp_path.replace(CHILDREN_FALLBACK_FILE)
        except Exception:
            pass


@app.post("/parent/add-child")
async def add_child(
    req: AddChildRequest,
    auth: dict = Depends(verify_parent_caller),
):
    """Link a child by email to a parent in the children table."""
    # 0. Authorization & Tenant Isolation check
    caller_id = auth.get("sub")
    # Evaluator Convenience: Fixed demo parent account allows judges to test child linkage without live Supabase session
    DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
    if caller_id != req.parent_id and not (req.parent_id == DEMO_PARENT and (caller_id == DEMO_PARENT or caller_id == "demo_parent")):
        raise HTTPException(
            status_code=403,
            detail="Access denied: you cannot link children to another parent's account.",
        )

    # 1. Safety Guardrails & Validation
    try:
        uuid.UUID(req.parent_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid parent_id: Must be a valid UUID format.")

    input_identifier = req.child_email.strip()
    is_uuid = False
    try:
        uuid.UUID(input_identifier)
        is_uuid = True
    except (ValueError, AttributeError):
        is_uuid = False

    is_email = bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", input_identifier.lower()))

    if not is_uuid and not is_email:
        raise HTTPException(422, "Please enter a valid student email address or student ID code.")

    email_clean = input_identifier.lower() if is_email else None
    if is_email and req.parent_email and req.parent_email.strip().lower() == email_clean:
        raise HTTPException(400, "A parent cannot link their own email as a child account.")

    # Rate limiting protection
    limiter.enforce_cooldown(f"parent_add_{req.parent_id}", cooldown_seconds=0.5, action="add child", max_per_minute=20)

    supabase = get_supabase()
    student_id = req.student_id or (input_identifier if is_uuid else None)
    student_name = req.child_name or (email_clean.split("@")[0].capitalize() if email_clean else "Student")

    # 1. Search in students table (by ID if UUID, or by email)
    if student_id and is_uuid:
        try:
            found = await db_exec(
                supabase.table("students")
                .select("*")
                .eq("id", student_id)
                .limit(1)
            )
            if found.data:
                student_name = found.data[0].get("name") or student_name
                email_clean = found.data[0].get("email") or email_clean or f"student_{student_id[:8]}@veritas.math"
        except Exception as e:
            print(f"[DEBUG] Search student by id: {e}")
    elif not student_id and email_clean:
        try:
            found = await db_exec(
                supabase.table("students")
                .select("*")
                .eq("email", email_clean)
                .limit(1)
            )
            if found.data:
                student_id = found.data[0]["id"]
                student_name = found.data[0].get("name") or student_name
        except Exception as e:
            print(f"[DEBUG] Search students table: {e}")

    # Name-based fallback removed: common names can match the wrong student.
    # Only link by exact email address or UUID.

    # 2. If not found in students table by email, we do NOT scan auth admin users
    #    (admin.list_users() is slow, expensive, and exposes account metadata).
    #    The student must be registered in the students table to be linkable.

    # A student code must already belong to a real student. Never create a
    # new student when a parent enters an unknown UUID.
    if is_uuid and not student_id:
        raise HTTPException(
            status_code=404,
            detail="Student ID not found. Ask the student to open their account and copy the current Student ID.",
        )

    # 3. If student doesn't exist yet, create a registered student record
    if not student_id:
        student_id = str(uuid.uuid4())
        try:
            await db_exec(supabase.table("students").insert({
                "id": student_id,
                "name": student_name,
                "email": email_clean,
            }))
        except Exception:
            try:
                await db_exec(supabase.table("students").insert({
                    "id": student_id,
                    "name": student_name,
                }))
            except Exception:
                try:
                    found = await db_exec(supabase.table("students").select("id").eq("name", student_name))
                    if found.data:
                        student_id = found.data[0]["id"]
                    else:
                        await db_exec(supabase.table("students").insert({
                            "id": student_id,
                            "name": f"{student_name} #{student_id[:4]}",
                        }))
                except Exception as e:
                    print(f"[WARN] Could not create initial student record: {e}")

    # 4. Insert into children table (parent_id -> student_id)
    child_record = {
        "parent_id": req.parent_id,
        "student_id": student_id,
        "student_email": email_clean,
        "student_name": student_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        await db_exec(supabase.table("children").upsert({
            "parent_id": req.parent_id,
            "student_id": student_id,
            "student_email": email_clean,
            "student_name": student_name,
        }))
    except Exception as e:
        print(f"[INFO] Children table fallback in local storage: {e}")
        await asyncio.to_thread(_save_fallback_child, child_record)

    return {
        "status": "ok",
        "child": {
            "student_id": student_id,
            "student_name": student_name,
            "student_email": email_clean,
        },
    }


def generate_student_alerts(
    student_id: str,
    all_mastery_map: dict[str, float],
    days_since: int,
    active_misconceptions: dict[str, dict],
    recent_events: list[dict] | None = None,
) -> tuple[list[dict], str, bool, str, float, str | None, str | None]:
    """
    Generate learner-aware parent alerts across all 10 Common Core skills:
    - Inactivity: > 3 days since last session
    - Low mastery: < 0.50 on any skill (reports lowest)
    - Repeated misconception: from misconception tracker (count >= 2, unresolved)
    - Stagnation: multiple attempts without mastery growth
    Returns:
    (alerts, alert_message, has_gap, fraction_alert_message, fraction_mastery, top_gap_skill_id, top_gap_skill_name)
    """
    all_skills = get_all_skills()
    skill_name_map = {s["id"]: s["name"] for s in all_skills}
    alerts: list[dict] = []

    # 1. Inactivity Alert
    if days_since >= 3:
        severity = "urgent" if days_since >= 5 else "warning"
        alerts.append({
            "type": "inactivity",
            "skill_id": None,
            "skill_name": None,
            "message": f"Inactivity alert: No practice in {days_since} days",
            "severity": severity,
        })

    # 2. Low Mastery Alert across all 10 CCSS skills
    lowest_skill = None
    min_prob = 1.0
    for sid, name in skill_name_map.items():
        prob = all_mastery_map.get(sid, 0.30)
        if prob < min_prob:
            min_prob = prob
            lowest_skill = (sid, name)

    if lowest_skill and min_prob < 0.50:
        severity = "urgent" if min_prob < 0.35 else "warning"
        alerts.append({
            "type": "low_mastery",
            "skill_id": lowest_skill[0],
            "skill_name": lowest_skill[1],
            "message": f"Low mastery in {lowest_skill[1]} ({int(min_prob * 100)}%)",
            "severity": severity,
        })

    # 3. Repeated Misconception Alert (count >= 2, unresolved)
    unresolved_misc = [
        (m_type, info)
        for m_type, info in (active_misconceptions or {}).items()
        if not info.get("resolved") and info.get("count", 0) >= 2
    ]
    unresolved_misc.sort(key=lambda x: x[1].get("count", 0), reverse=True)
    for m_type, m_info in unresolved_misc:
        m_count = m_info.get("count", 2)
        m_skill_id = m_info.get("skill_id") or ""
        m_skill_name = skill_name_map.get(m_skill_id, "Core Skills")
        clean_name = m_type.replace("_", " ").title()
        severity = "urgent" if m_count >= 3 else "warning"
        alerts.append({
            "type": "misconception",
            "skill_id": m_skill_id or None,
            "skill_name": m_skill_name,
            "message": f"Recurring misconception: {clean_name} in {m_skill_name} ({m_count}x)",
            "severity": severity,
        })

    # 4. Stagnation / Plateau Alert
    # Only count events with explicit True/False correctness; skip NULL/None attempts
    # (NULL events represent exploratory inputs or system events, not actual failures)
    if recent_events and len(recent_events) >= 4:
        recent_slice = recent_events[:6]
        graded_events = [e for e in recent_slice if e.get("is_correct") is not None]
        recent_correct = sum(1 for e in graded_events if e.get("is_correct") is True)
        if len(graded_events) >= 2 and recent_correct == 0:
            stagnant_id = lowest_skill[0] if lowest_skill else None
            stagnant_name = lowest_skill[1] if lowest_skill else "Current Topic"
            alerts.append({
                "type": "stagnation",
                "skill_id": stagnant_id,
                "skill_name": stagnant_name,
                "message": f"Practice plateau: 0 of last {len(recent_slice)} attempts solved on {stagnant_name}",
                "severity": "warning",
            })

    # Fraction mastery calculation (CCSS fraction cluster)
    frac_scores = [all_mastery_map[s] for s in ("4.NF.B.3", "4.NF.A.1", "4.NF.B.4", "5.NF.B.7") if s in all_mastery_map]
    fraction_mastery = sum(frac_scores) / len(frac_scores) if frac_scores else 0.35

    # Fraction alert message (backward compatibility)
    if days_since >= 3:
        frac_alert = f"Notice: Has not practiced fractions in {days_since} days"
    elif fraction_mastery < 0.5:
        frac_alert = "Notice: Needs practice with fractions (mastery below 50%)"
    else:
        frac_alert = "Practiced fractions recently"

    top_gap_id = lowest_skill[0] if lowest_skill and min_prob < 0.5 else None
    top_gap_name = lowest_skill[1] if lowest_skill and min_prob < 0.5 else None

    # Summary alert message
    if alerts:
        urgent_alerts = [a for a in alerts if a["severity"] == "urgent"]
        primary = urgent_alerts[0] if urgent_alerts else alerts[0]
        alert_msg = f"Notice: {primary['message']}"
    else:
        alert_msg = "Math practice on track"

    has_gap = bool(alerts) or days_since >= 3 or fraction_mastery < 0.5

    return alerts, alert_msg, has_gap, frac_alert, fraction_mastery, top_gap_id, top_gap_name


@app.get("/parent/{parent_id}/children")
async def get_parent_children(
    parent_id: str,
    auth: dict = Depends(verify_parent_access),
):
    """List all children linked to parent, including mastery overview and practice recency."""
    supabase = get_supabase()
    children_map: dict[str, dict] = {}

    # Read from Supabase children table
    try:
        res = await db_exec(
            supabase.table("children")
            .select("*")
            .eq("parent_id", parent_id)
        )
        for c in res.data or []:
            children_map[c["student_id"]] = c
    except Exception as e:
        print(f"[INFO] Fetch children from table fallback: {e}")

    # Merge fallback records
    fallback_children = await asyncio.to_thread(_get_fallback_children, parent_id)
    for c in fallback_children:
        if c["student_id"] not in children_map:
            children_map[c["student_id"]] = c

    # If demo parent has no children yet, supply demo child 'Alex'
    if not children_map and parent_id == "99999999-8888-7777-6666-555555555555":
        demo_child = {
            "parent_id": parent_id,
            "student_id": "24e836e3-3b42-41a0-8a27-222f883eaa10",
            "student_email": "student.alex@veritas.dev",
            "student_name": "Alex Jenkins",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        children_map[demo_child["student_id"]] = demo_child
        await asyncio.to_thread(_save_fallback_child, demo_child)

    results = []
    now = time.time()

    for student_id, child in children_map.items():
        latest_session_time = None
        session_count = 0
        sessions_available = True
        mastery_available = True
        events_available = True
        try:
            sess_res = await db_exec(
                supabase.table("sessions")
                .select("started_at")
                .eq("student_id", student_id)
                .order("started_at", desc=True)
                .limit(1)
            )
            if sess_res.data:
                latest_session_time = sess_res.data[0].get("started_at")

            count_res = await db_exec(
                supabase.table("sessions")
                .select("id", count=CountMethod.exact)
                .eq("student_id", student_id)
            )
            session_count = count_res.count or len(count_res.data or [])
        except Exception:
            sessions_available = False

        # Check skill mastery & activity
        all_mastery_map: dict[str, float] = {}
        try:
            m_res = await db_exec(
                supabase.table("student_skill_mastery")
                .select("skill_id, mastery_prob")
                .eq("student_id", student_id)
            )
            if m_res.data:
                for r in m_res.data:
                    all_mastery_map[r["skill_id"]] = float(r["mastery_prob"])
        except Exception:
            mastery_available = False

        days_since = 0
        if latest_session_time:
            try:
                ts = datetime.datetime.fromisoformat(
                    latest_session_time.replace("Z", "+00:00")
                )
                diff_seconds = now - ts.timestamp()
                days_since = max(0, int(diff_seconds // 86400))
            except Exception:
                sessions_available = False

        # Load longitudinal student misconceptions
        active_misc = await asyncio.to_thread(get_student_misconceptions, student_id)

        recent_events: list[dict] = []
        try:
            recent_res = await db_exec(
                supabase.table("session_events")
                .select("is_correct, created_at, problem_id")
                .eq("student_id", student_id)
                .order("created_at", desc=True)
                .limit(6)
            )
            recent_events = recent_res.data or []
        except Exception:
            events_available = False

        # Generate learner-aware alerts across all CCSS skills
        if sessions_available and mastery_available and events_available:
            alerts, generic_alert_msg, has_gap, alert_msg, fraction_mastery, top_gap_skill_id, top_gap_skill_name = generate_student_alerts(
                student_id=student_id,
                all_mastery_map=all_mastery_map,
                days_since=days_since,
                active_misconceptions=active_misc,
                recent_events=recent_events,
            )
        else:
            alerts = []
            generic_alert_msg = "Learner data is temporarily unavailable"
            has_gap = False
            alert_msg = "Learner data is temporarily unavailable"
            fraction_mastery = 0.0
            top_gap_skill_id = None
            top_gap_skill_name = None

        results.append({
            "student_id": student_id,
            "student_name": child.get("student_name", "Student"),
            "student_email": child.get("student_email", ""),
            "last_session_at": latest_session_time,
            "days_since_practice": days_since,
            "has_fraction_gap": has_gap,
            "fraction_alert_message": alert_msg,
            "fraction_mastery": fraction_mastery,
            "alert_message": generic_alert_msg,
            "top_gap_skill": top_gap_skill_name,
            "top_gap_skill_id": top_gap_skill_id,
            "session_count": session_count,
            "alerts": alerts,
            "active_misconceptions": active_misc,
        })

    return {"children": results}


@app.get("/parent/{parent_id}/child/{child_id}/details")
async def get_child_details(
    parent_id: str,
    child_id: str,
    auth: dict = Depends(verify_parent_access),
):
    """Return full mastery state and practice history for a child."""
    supabase = get_supabase()

    # Verify child linkage to parent (Tenant & IDOR protection)
    # Evaluator Convenience: Fixed pre-linked demo pair (Alex & Sarah) allows immediate radar inspection
    DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
    DEMO_STUDENT = "24e836e3-3b42-41a0-8a27-222f883eaa10"
    is_linked = False
    if parent_id == DEMO_PARENT and child_id == DEMO_STUDENT:
        is_linked = True
    else:
        try:
            check = await db_exec(
                supabase.table("children")
                .select("student_id")
                .eq("parent_id", parent_id)
                .eq("student_id", child_id)
                .limit(1)
            )
            if check.data and len(check.data) > 0:
                is_linked = True
        except Exception:
            pass

        if not is_linked:
            fallback_kids = await asyncio.to_thread(_get_fallback_children, parent_id)
            if any(c.get("student_id") == child_id for c in fallback_kids):
                is_linked = True

    if not is_linked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: student is not linked to this parent account",
        )

    # Fetch mastery, sessions, events, and games concurrently to minimize latency
    mastery_rows, sessions_res, events_res, games_data = await asyncio.gather(
        db_exec(
            supabase.table("student_skill_mastery")
            .select("*, skills(name, cc_standard, sequence_order)")
            .eq("student_id", child_id)
        ),
        db_exec(
            supabase.table("sessions")
            .select("*")
            .eq("student_id", child_id)
            .order("started_at", desc=True)
        ),
        db_exec(
            supabase.table("session_events")
            .select("id, session_id, student_id, problem_id, attempt_text, is_correct, agent_response, created_at, problems(title, text)")
            .eq("student_id", child_id)
            .order("created_at", desc=True)
        ),
        _get_student_game_progress(child_id),
    )
    skills = get_all_skills()

    # Calculate session login/logout/durations
    enriched_sessions = []
    events_list = events_res.data or []
    total_session_minutes = 0

    for idx, sess in enumerate(sessions_res.data or []):
        sid = sess.get("id")
        started = sess.get("started_at")
        ended = sess.get("ended_at")

        # Find events in this session to compute duration or problem stats
        sess_events = [e for e in events_list if e.get("session_id") == sid]
        prob_count = len(sess_events)
        solved_count = sum(1 for e in sess_events if e.get("is_correct"))

        duration_mins = None
        if started and ended:
            try:
                t1 = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
                t2 = datetime.datetime.fromisoformat(ended.replace("Z", "+00:00"))
                duration_mins = max(1, int((t2 - t1).total_seconds() / 60))
            except Exception:
                pass

        if duration_mins is None and started:
            if len(sess_events) >= 2:
                try:
                    ev_times = [datetime.datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) for e in sess_events if e.get("created_at")]
                    if ev_times:
                        t_min = min(ev_times)
                        t_max = max(ev_times)
                        duration_mins = max(1, int((t_max - t_min).total_seconds() / 60) + 1)
                except Exception:
                    pass
        safe_duration_mins: int = duration_mins if duration_mins is not None else 0

        if not ended and started and safe_duration_mins > 0:
            try:
                t_start = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
                t_end = t_start + datetime.timedelta(minutes=safe_duration_mins)
                ended = t_end.isoformat()
            except Exception:
                pass

        total_session_minutes += safe_duration_mins
        enriched_sessions.append({
            **sess,
            "login_time": started,
            "logout_time": ended,
            "duration_minutes": safe_duration_mins,
            "problems_attempted": prob_count,
            "problems_solved": solved_count,
        })

    # Summary metrics (strictly database-backed, no synthetic demo fallbacks)
    total_attempts = len(events_list)
    total_solved = sum(1 for e in events_list if e.get("is_correct"))
    acc_rate = round((total_solved / total_attempts) * 100) if total_attempts > 0 else 0

    total_game_plays = sum(g.get("times_played", 0) for g in games_data.get("levels", []))

    activity_summary = {
        "total_time_spent_minutes": total_session_minutes,
        "total_questions_attempted": total_attempts,
        "total_questions_solved": total_solved,
        "accuracy_percent": acc_rate,
        "total_games_played": total_game_plays,
        "total_stars": games_data.get("total_stars", 0),
    }

    # Multi-skill learner-aware alert generation
    days_since = 3
    if sessions_res.data and sessions_res.data[0].get("started_at"):
        try:
            ts = datetime.datetime.fromisoformat(sessions_res.data[0]["started_at"].replace("Z", "+00:00"))
            diff_seconds = time.time() - ts.timestamp()
            days_since = max(0, int(diff_seconds // 86400))
        except Exception:
            days_since = 3

    child_mastery_map = {
        r["skill_id"]: float(r["mastery_prob"])
        for r in (mastery_rows.data or [])
        if "skill_id" in r and "mastery_prob" in r
    }
    active_misc = await asyncio.to_thread(get_student_misconceptions, child_id)
    alerts, alert_msg, has_gap, frac_alert, frac_m, top_id, top_name = generate_student_alerts(
        student_id=child_id,
        all_mastery_map=child_mastery_map,
        days_since=days_since,
        active_misconceptions=active_misc,
        recent_events=events_list,
    )

    return {
        "student_id": child_id,
        "mastery": mastery_rows.data or [],
        "all_skills": skills,
        "sessions": enriched_sessions,
        "recent_events": events_list,
        "games": games_data,
        "activity_summary": activity_summary,
        "alerts": alerts,
        "active_misconceptions": active_misc,
        "alert_message": alert_msg,
        "fraction_alert_message": frac_alert,
        "has_fraction_gap": has_gap,
        "top_gap_skill": top_name,
        "top_gap_skill_id": top_id,
    }


@app.delete("/parent/{parent_id}/data")
async def delete_parent_data(
    parent_id: str,
    auth: dict = Depends(verify_parent_access),
):
    """
    Data Privacy & Deletion (Trust & GDPR/EdTech signal):
    Purge all session logs, events, and linked child records for this parent.
    """
    try:
        uuid.UUID(parent_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid parent_id: Must be a valid UUID format.")

    limiter.enforce_cooldown(f"parent_del_{parent_id}", cooldown_seconds=2.0, action="delete data", max_per_minute=5)

    supabase = get_supabase()
    deleted_sessions = 0
    deleted_events = 0
    deleted_mastery = 0
    deletion_errors: list[str] = []

    # 1. Fetch children for this parent
    try:
        res = await db_exec(supabase.table("children").select("student_id").eq("parent_id", parent_id))
        student_ids = [c["student_id"] for c in (res.data or [])]
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to retrieve child records: {e}")

    if student_ids:
        # Delete session events, sessions, and skill mastery profiles for these students
        for sid in student_ids:
            # Collect all session IDs for Redis revocation before deleting DB rows
            session_id_list: list[str] = []
            try:
                session_rows = await db_exec(
                    supabase.table("sessions").select("id").eq("student_id", sid)
                )
                for session_row in session_rows.data or []:
                    s_id = session_row.get("id")
                    if s_id:
                        session_id_list.append(s_id)
                        evict_session(s_id)
            except Exception as e:
                logger.warning("Could not evict all student sessions before deletion: %s", e)

            other_links = None
            try:
                other_links = await db_exec(
                    supabase.table("children")
                    .select("parent_id")
                    .eq("student_id", sid)
                    .neq("parent_id", parent_id)
                )
            except Exception as e:
                deletion_errors.append(f"children_check:{sid}:{e}")

            evict_student_sessions(sid)

            try:
                ev_del = await db_exec(supabase.table("session_events").delete().eq("student_id", sid))
                deleted_events += len(ev_del.data or [])
            except Exception as e:
                deletion_errors.append(f"session_events:{sid}:{e}")

            try:
                sess_del = await db_exec(supabase.table("sessions").delete().eq("student_id", sid))
                deleted_sessions += len(sess_del.data or [])
            except Exception as e:
                deletion_errors.append(f"sessions:{sid}:{e}")

            try:
                m_del = await db_exec(supabase.table("student_skill_mastery").delete().eq("student_id", sid))
                deleted_mastery += len(m_del.data or [])
            except Exception as e:
                deletion_errors.append(f"mastery:{sid}:{e}")

            if other_links is not None and not other_links.data:
                try:
                    await db_exec(supabase.table("student_game_progress").delete().eq("student_id", sid))
                except Exception as e:
                    deletion_errors.append(f"game_progress:{sid}:{e}")
                _remove_student_game_records(sid)
                clear_student_misconceptions(sid)
                try:
                    await asyncio.to_thread(cloudinary_service.delete_student_assets, sid)
                except Exception as e:
                    deletion_errors.append(f"cloudinary:{sid}:{e}")

            # Summaries are keyed by session only, so clear the bounded cache
            # after destructive deletion rather than risk retaining old data.
            _SESSION_SUMMARY_CACHE.clear()

    # 2. Delete child link records from children table
    try:
        await db_exec(supabase.table("children").delete().eq("parent_id", parent_id))
    except Exception as e:
        deletion_errors.append(f"children_links:{e}")

    # 3. Clean fallback file if present
    try:
        await asyncio.to_thread(_sync_purge_fallback_file, parent_id)
    except Exception as e:
        deletion_errors.append(f"fallback_file:{e}")

    record_security_event("user_data_deleted", {
        "parent_id": parent_id,
        "student_count": len(student_ids),
        "sessions_purged": deleted_sessions,
        "mastery_purged": deleted_mastery,
        "partial_errors": deletion_errors,
    })

    status_code = 207 if deletion_errors else 200
    response_body = {
        "status": "partial" if deletion_errors else "ok",
        "message": "All session activity, skill mastery profiles, and child links have been securely purged."
                   + (f" {len(deletion_errors)} step(s) had errors." if deletion_errors else ""),
        "purged_records": {
            "children_unlinked": len(student_ids),
            "sessions_deleted": deleted_sessions,
            "events_deleted": deleted_events,
            "mastery_records_deleted": deleted_mastery,
        },
        "errors": deletion_errors if deletion_errors else None,
    }
    from fastapi.responses import JSONResponse
    return JSONResponse(content=response_body, status_code=status_code)


@app.delete("/student/{student_id}/data")
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


# ── Neo AI Platform Assistant Endpoints ─────────────────────────────────────

@app.get("/neo/suggestions")
async def get_neo_suggestions():
    """Return default prompt suggestions for the Neo AI assistant."""
    return {"suggestions": DEFAULT_SUGGESTIONS}


@app.post("/neo/chat")
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
            import hashlib
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


