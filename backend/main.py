"""
FastAPI Backend — AI Socratic Tutor Entrypoint.
Modularized application entry point mounting domain routers from backend/routes/.
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import sys
import warnings

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

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from auth import is_session_secret_configured
from routes.common import (
    DEMO_STUDENT_ID,
    db_exec,
    get_orchestrator_graph,
    set_orchestrator_graph,
)
from routes.games import GAME_LEVELS_CONFIG, router as games_router
from routes.health import router as health_router
from routes.neo import router as neo_router
from routes.parent import generate_student_alerts, router as parent_router
from routes.session import router as session_router
from routes.student import router as student_router

logger = logging.getLogger("veritas-backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        graph = get_orchestrator_graph()
        set_orchestrator_graph(graph)
        print("[INFO] LangGraph orchestrator compiled successfully on startup.")
    except Exception as e:
        set_orchestrator_graph(None)
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
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    # Pre-check upload size before multipart parsing to prevent memory abuse at the transport layer
    if request.url.path == "/session/upload-work":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > 10 * 1024 * 1024 + 1:
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


# Mount modular domain routers
app.include_router(health_router)
app.include_router(games_router)
app.include_router(session_router)
app.include_router(student_router)
app.include_router(parent_router)
app.include_router(neo_router)

# Re-export backward-compatible legacy symbols for existing tests and scripts
__all__ = [
    "app",
    "get_orchestrator_graph",
    "DEMO_STUDENT_ID",
    "db_exec",
    "generate_student_alerts",
    "GAME_LEVELS_CONFIG",
]
