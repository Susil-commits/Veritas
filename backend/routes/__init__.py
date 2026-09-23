"""Domain route modules for the Veritas FastAPI application."""

from routes.common import DEMO_STUDENT_ID, db_exec, get_orchestrator_graph
from routes.games import router as games_router
from routes.health import router as health_router
from routes.neo import router as neo_router
from routes.parent import generate_student_alerts, router as parent_router
from routes.session import router as session_router
from routes.student import router as student_router

__all__ = [
    "health_router",
    "games_router",
    "session_router",
    "student_router",
    "parent_router",
    "neo_router",
    "DEMO_STUDENT_ID",
    "db_exec",
    "get_orchestrator_graph",
    "generate_student_alerts",
]
