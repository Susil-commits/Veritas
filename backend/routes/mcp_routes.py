"""
Model Context Protocol (MCP) Router for Veritas.

Provides HTTP & SSE endpoints for external agents (Cursor, Claude Desktop, Antigravity, LMSs)
to interact with Veritas tools, resources, and Socratic prompts over the standard MCP protocol.
"""
import asyncio
import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

try:
    from backend.mcp.server import VeritasMCPServer
except ImportError:
    from mcp.server import VeritasMCPServer
from routes.common import SSE_HEADERS

logger = logging.getLogger("veritas-backend.mcp_router")

router = APIRouter(prefix="/mcp", tags=["mcp"])
mcp_server = VeritasMCPServer()


@router.post("", summary="Model Context Protocol JSON-RPC 2.0 Endpoint")
async def handle_mcp_jsonrpc(request: Request):
    """
    Direct JSON-RPC 2.0 handler for standard Model Context Protocol (MCP) clients.
    Supports initialize, tools/list, tools/call, resources/list, resources/read, prompts/list, prompts/get.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Invalid JSON: {e}"}}
        )

    # If payload is batch (list) or single request (dict)
    if isinstance(payload, list):
        responses = [mcp_server.handle_request(req) for req in payload]
        return JSONResponse(content=responses)
    elif isinstance(payload, dict):
        response = mcp_server.handle_request(payload)
        return JSONResponse(content=response)
    else:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        )


@router.get("/tools", summary="List Available MCP Tools")
async def list_mcp_tools():
    """Returns all tools exported by the Veritas MCP server."""
    req = {"jsonrpc": "2.0", "id": "rest_tools", "method": "tools/list", "params": {}}
    resp = mcp_server.handle_request(req)
    return resp.get("result", {})


@router.get("/resources", summary="List Available MCP Resources")
async def list_mcp_resources():
    """Returns all resources exported by the Veritas MCP server."""
    req = {"jsonrpc": "2.0", "id": "rest_resources", "method": "resources/list", "params": {}}
    resp = mcp_server.handle_request(req)
    return resp.get("result", {})


@router.get("/prompts", summary="List Available MCP Prompts")
async def list_mcp_prompts():
    """Returns all prompt templates exported by the Veritas MCP server."""
    req = {"jsonrpc": "2.0", "id": "rest_prompts", "method": "prompts/list", "params": {}}
    resp = mcp_server.handle_request(req)
    return resp.get("result", {})


@router.get("/sse", summary="Server-Sent Events MCP Transport Stream")
async def mcp_sse_transport(request: Request, once: bool = False):
    """
    Standard Server-Sent Events (SSE) transport for MCP streaming connections.
    """
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
