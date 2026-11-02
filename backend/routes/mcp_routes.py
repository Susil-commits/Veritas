"""
Model Context Protocol (MCP) Router for Veritas.

Provides HTTP & SSE endpoints for external agents (Cursor, Claude Desktop, Antigravity, LMSs)
to interact with Veritas tools, resources, and Socratic prompts over the standard MCP protocol.
"""
import os
import asyncio
import hmac
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

try:
    from backend.mcp.server import VeritasMCPServer
except ImportError:
    from mcp.server import VeritasMCPServer
from rate_limiter import limiter
from routes.common import SSE_HEADERS

logger = logging.getLogger("veritas-backend.mcp_router")

router = APIRouter(prefix="/mcp", tags=["mcp"])
mcp_server = VeritasMCPServer()

MCP_TIMEOUT_SECONDS = 5.0


def _verify_mcp_auth(request: Request, authorization: Optional[str] = None, x_api_key: Optional[str] = None):
    """Enforce authentication on MCP endpoints. Fails closed (HTTP 503) if VERITAS_MCP_API_KEY is not configured."""
    is_prod = (
        os.getenv("ENVIRONMENT", "").lower() == "production"
        or os.getenv("RENDER") is not None
    )
    is_test = (
        os.getenv("VERITAS_TEST_MODE", "").lower() == "true"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
    )
    expected_key = os.getenv("VERITAS_MCP_API_KEY")

    if not expected_key:
        if is_test and not is_prod:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP service is disabled: VERITAS_MCP_API_KEY environment variable is not configured.",
        )

    token = authorization.replace("Bearer ", "").strip() if authorization else (x_api_key.strip() if x_api_key else "")
    if not token or not hmac.compare_digest(token.encode("utf-8"), expected_key.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing MCP API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("", summary="Model Context Protocol JSON-RPC 2.0 Endpoint")
async def handle_mcp_jsonrpc(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Direct JSON-RPC 2.0 handler for standard Model Context Protocol (MCP) clients.
    Runs asynchronously off the event loop with strict timeout and execution sandboxing.
    """
    _verify_mcp_auth(request, authorization, x_api_key)

    is_test = os.getenv("VERITAS_TEST_MODE", "").lower() == "true"
    if not is_test:
        client_ip = request.client.host if request.client else "unknown_mcp_client"
        limiter.enforce_cooldown(
            key=f"mcp_req_{client_ip}",
            cooldown_seconds=0.05,
            action="MCP request",
            max_per_minute=200,
        )

    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Invalid JSON: {e}"}}
        )

    async def _safe_execute(req: dict) -> dict:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(mcp_server.handle_request, req),
                timeout=MCP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            req_id = req.get("id") if isinstance(req, dict) else None
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": f"Execution timed out: tool evaluation exceeded {MCP_TIMEOUT_SECONDS}s safety limit."
                }
            }
        except Exception as err:
            req_id = req.get("id") if isinstance(req, dict) else None
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"Internal MCP server error: {err}"}
            }

    # If payload is batch (list) or single request (dict)
    if isinstance(payload, list):
        responses = [await _safe_execute(req) for req in payload]
        return JSONResponse(content=responses)
    elif isinstance(payload, dict):
        response = await _safe_execute(payload)
        return JSONResponse(content=response)
    else:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        )


@router.get("/tools", summary="List Available MCP Tools")
async def list_mcp_tools(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Returns all tools exported by the Veritas MCP server."""
    _verify_mcp_auth(request, authorization, x_api_key)
    req = {"jsonrpc": "2.0", "id": "rest_tools", "method": "tools/list", "params": {}}
    resp = await asyncio.to_thread(mcp_server.handle_request, req)
    return resp.get("result", {})


@router.get("/resources", summary="List Available MCP Resources")
async def list_mcp_resources(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Returns all resources exported by the Veritas MCP server."""
    _verify_mcp_auth(request, authorization, x_api_key)
    req = {"jsonrpc": "2.0", "id": "rest_resources", "method": "resources/list", "params": {}}
    resp = await asyncio.to_thread(mcp_server.handle_request, req)
    return resp.get("result", {})


@router.get("/prompts", summary="List Available MCP Prompts")
async def list_mcp_prompts(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Returns all prompt templates exported by the Veritas MCP server."""
    _verify_mcp_auth(request, authorization, x_api_key)
    req = {"jsonrpc": "2.0", "id": "rest_prompts", "method": "prompts/list", "params": {}}
    resp = await asyncio.to_thread(mcp_server.handle_request, req)
    return resp.get("result", {})


@router.get("/sse", summary="Server-Sent Events MCP Transport Stream")
async def mcp_sse_transport(
    request: Request,
    once: bool = False,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Standard Server-Sent Events (SSE) transport for MCP streaming connections.
    """
    _verify_mcp_auth(request, authorization, x_api_key)
    client_ip = request.client.host if request.client else "unknown_sse_client"
    limiter.enforce_cooldown(
        key=f"mcp_sse_{client_ip}",
        cooldown_seconds=1.0,
        action="MCP SSE connect",
        max_per_minute=30,
    )

    async def sse_generator():
        # Yield initial endpoint declaration event required by MCP SSE specification
        init_event = {
            "type": "endpoint",
            "endpoint": "/mcp"
        }
        yield f"event: endpoint\ndata: {json.dumps(init_event)}\n\n"

        if once:
            return

        # Heartbeat loop
        while not await request.is_disconnected():
            try:
                await asyncio.sleep(15)
                yield ": ping\n\n"
            except asyncio.CancelledError:
                break

    return StreamingResponse(sse_generator(), media_type="text/event-stream", headers=SSE_HEADERS)
