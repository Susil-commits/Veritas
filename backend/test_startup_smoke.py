"""
Veritas Startup & Lifespan Smoke Test
Verifies that:
1. LangGraph state machine compiles without errors.
2. FastAPI app initializes cleanly through its lifespan.
3. Health check endpoints (/ and /health and /health/full) respond with 200 OK.
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
        getattr(sys.stderr, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from graph.orchestrator import build_graph
from main import app, get_orchestrator_graph


def test_langgraph_compilation():
    print("\n[SMOKE 1] Testing LangGraph state machine compilation...")
    graph = build_graph()
    assert graph is not None, "build_graph() returned None"
    print(f"  [OK] LangGraph successfully compiled: {type(graph).__name__}")


def test_fastapi_startup_and_health():
    print("\n[SMOKE 2] Testing FastAPI lifespan and health endpoints via TestClient...")
    with TestClient(app) as client:
        # Test root endpoint
        res_root = client.get("/")
        assert res_root.status_code == 200, f"Root endpoint returned {res_root.status_code}"
        assert res_root.json().get("status") == "ok"
        print("  [OK] Root route (/) returned 200 OK")

        # Test simple liveness probe used by Render healthCheckPath
        res_health = client.get("/health")
        assert res_health.status_code == 200, f"/health returned {res_health.status_code}"
        assert res_health.json().get("status") == "ok"
        print("  [OK] Render liveness probe (/health) returned 200 OK")

        # Test full health endpoint
        res_full = client.get("/health/full")
        assert res_full.status_code == 200, f"/health/full returned {res_full.status_code}"
        data = res_full.json()
        assert "services" in data
        assert "orchestrator" in data["services"]
        assert data["services"]["orchestrator"] is True
        print(f"  [OK] Full readiness probe (/health/full) returned 200 OK (orchestrator: {data['services']['orchestrator']})")

    print("\n=== STARTUP SMOKE TEST PASSED! ===")


if __name__ == "__main__":
    test_langgraph_compilation()
    test_fastapi_startup_and_health()
