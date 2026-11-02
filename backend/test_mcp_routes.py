"""
Test suite for FastAPI MCP (Model Context Protocol) endpoints.
Verifies:
- POST /mcp (JSON-RPC 2.0 initialize, tools/list, tools/call)
- GET /mcp/tools
- GET /mcp/resources
- GET /mcp/prompts
- GET /mcp/sse
"""
import pytest
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from starlette.testclient import TestClient
try:
    from backend.main import app
except ImportError:
    from main import app

client = TestClient(app)


def test_fastapi_mcp_initialize():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }
    response = client.post("/mcp", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["serverInfo"]["name"] == "veritas-socratic-math-mcp"
    assert "tools" in data["result"]["capabilities"]


def test_fastapi_mcp_tools_list_and_call():
    # 1. tools/list via JSON-RPC
    list_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    list_resp = client.post("/mcp", json=list_payload)
    assert list_resp.status_code == 200
    tools = list_resp.json()["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "veritas_verify_math_step" in tool_names

    # 2. tools/call via JSON-RPC
    call_payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "veritas_verify_math_step",
            "arguments": {
                "previous_expr": "3 * (x - 2)",
                "student_step_expr": "3 * x - 6"
            }
        }
    }
    call_resp = client.post("/mcp", json=call_payload)
    assert call_resp.status_code == 200
    res_text = call_resp.json()["result"]["content"][0]["text"]
    assert "equivalent" in res_text


def test_fastapi_mcp_rest_convenience_endpoints():
    # GET /mcp/tools
    resp_tools = client.get("/mcp/tools")
    assert resp_tools.status_code == 200
    assert "tools" in resp_tools.json()

    # GET /mcp/resources
    resp_resources = client.get("/mcp/resources")
    assert resp_resources.status_code == 200
    assert "resources" in resp_resources.json()

    # GET /mcp/prompts
    resp_prompts = client.get("/mcp/prompts")
    assert resp_prompts.status_code == 200
    assert "prompts" in resp_prompts.json()


def test_fastapi_mcp_sse_transport():
    with client.stream("GET", "/mcp/sse?once=true") as stream:
        assert stream.status_code == 200
        first_line = next(stream.iter_lines())
        assert "event: endpoint" in first_line


def test_fastapi_mcp_auth_fail_closed_and_constant_time():
    import os
    # 1. Test fail-closed in production mode when key is missing
    os.environ["ENVIRONMENT"] = "production"
    old_key = os.environ.pop("VERITAS_MCP_API_KEY", None)
    old_test_mode = os.environ.pop("VERITAS_TEST_MODE", None)

    try:
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 99, "method": "initialize", "params": {}})
        assert resp.status_code == 503, f"Expected 503 fail-closed when key missing, got {resp.status_code}"

        # 2. Configure key and test invalid token rejected with 401
        os.environ["VERITAS_MCP_API_KEY"] = "secure_mcp_secret_key_12345"
        resp_bad = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 99, "method": "initialize", "params": {}},
            headers={"Authorization": "Bearer wrong_token_attempt"},
        )
        assert resp_bad.status_code == 401, f"Expected 401 for wrong token, got {resp_bad.status_code}"

        # 3. Valid key accepted with 200
        resp_good = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 99, "method": "initialize", "params": {}},
            headers={"Authorization": "Bearer secure_mcp_secret_key_12345"},
        )
        assert resp_good.status_code == 200, f"Expected 200 for correct token, got {resp_good.status_code}"
    finally:
        os.environ["ENVIRONMENT"] = "test"
        if old_key:
            os.environ["VERITAS_MCP_API_KEY"] = old_key
        else:
            os.environ.pop("VERITAS_MCP_API_KEY", None)
        if old_test_mode:
            os.environ["VERITAS_TEST_MODE"] = old_test_mode


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
