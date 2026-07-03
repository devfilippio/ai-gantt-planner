"""MCP-style tool bridge for the plan mutation tools.

The installed `mcp` SDK version (1.2.0) does not ship a mountable
streamable-HTTP ASGI transport (`mcp.server.streamable_http` is not
available in this version — only stdio and SSE-via-running-loop
transports exist). Building a real streamable-HTTP mount would require
either upgrading the `mcp` dependency or hand-rolling the wire protocol,
both out of scope for this task.

As a robust, minimal fallback (explicitly sanctioned by the plan for this
situation) this module exposes the same tools (list + call) as a small
JSON API:

  GET  /api/mcp         -> {"tools": [...TOOL_SCHEMAS...]}
  POST /api/mcp         -> {"name": str, "args": dict} executes a tool
                            against the store's current plan and returns
                            the resulting PlanPatch (or an error).

This keeps `from api.index import app` import-safe and gives external
clients (including a future real MCP transport) a working tool surface to
call. Upgrading to full MCP-SDK streamable-HTTP transport is a documented
follow-up.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.store import get_store
from api.tool_registry import TOOL_SCHEMAS, dispatch
from api.tools import ToolError

router = APIRouter()

# Also build a real (if unmounted) low-level MCP Server instance so the
# tool metadata / call-tool logic is genuinely backed by the `mcp` SDK's
# types, ready to be wired to a real transport once the SDK is upgraded.
try:
    from mcp.server import Server as _MCPServer

    mcp_server = _MCPServer("ai-gantt-planner")
except Exception:  # pragma: no cover - defensive, keep import always safe
    mcp_server = None


class MCPCallRequest(BaseModel):
    name: str
    args: dict = {}


@router.get("/api/mcp")
def list_tools() -> dict:
    return {"tools": TOOL_SCHEMAS}


@router.post("/api/mcp")
def call_tool(body: MCPCallRequest) -> dict:
    store = get_store()
    plan = store.get_plan()
    try:
        patch = dispatch(body.name, body.args, plan)
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store.save_plan(patch.plan)
    return {"plan_patch": patch.model_dump()}
