"""
Common utilities, database execution helpers, and shared state for Veritas routers.
"""
import time
import asyncio
import threading
import logging
from pathlib import Path
from typing import Any
from graph.orchestrator import build_graph

logger = logging.getLogger("veritas-backend")

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Demo student ID matching seeded database profile
DEMO_STUDENT_ID = "24e836e3-3b42-41a0-8a27-222f883eaa10"

# Server start timestamp for uptime reporting
_server_start_time = time.time()

# Thread-safe compiled LangGraph singleton orchestrator
_graph_lock = threading.Lock()
_graph: Any = None


def get_orchestrator_graph() -> Any:
    """Returns the singleton compiled LangGraph state machine orchestrator, building it on first access."""
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = build_graph()
    return _graph


def set_orchestrator_graph(graph: Any) -> None:
    """Explicitly set or reset the graph instance (used during startup lifespan)."""
    global _graph
    with _graph_lock:
        _graph = graph


# SSE Response headers to prevent proxy/CDN buffering (Render, Cloudflare, Nginx)
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Cache session summaries in memory to avoid redundant LLM calls
_SESSION_SUMMARY_CACHE: dict[str, Any] = {}


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
            if attempt < retries and any(err in str(e) for err in [
                "10035", "ReadError", "ConnectError", "timed out", "Timeout",
                "RemoteProtocolError", "ConnectionTerminated", "RemoteDisconnected"
            ]):
                await asyncio.sleep(0.15 * (attempt + 1))
                continue
            raise


def _public_problem(problem: dict | None) -> dict | None:
    """Strip internal solution fields and embeddings from a problem before returning to client."""
    if not problem:
        return None
    p = dict(problem)
    p.pop("answer", None)
    p.pop("expected_steps", None)
    p.pop("full_solution", None)
    p.pop("solution", None)
    p.pop("embedding", None)
    return p
