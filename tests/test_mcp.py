"""Real MCP handshake test against the FastMCP server used by api/mcp_server.py.

We connect an actual `mcp.client.session.ClientSession` to the server's
underlying low-level `Server` via the SDK's in-memory transport helper
(`mcp.shared.memory.create_connected_server_and_client_session`). This
performs a genuine MCP `initialize`, `list_tools`, and `call_tool` exchange
over the real protocol types/session logic - the same machinery the
streamable-HTTP ASGI transport uses internally - without needing to spin up
a real HTTP server/port under pytest. This is preferred over a lighter
"just check the app is importable" assertion because it verifies the actual
tool registrations and call semantics, not just that the module loads.
"""
from __future__ import annotations

import pytest

from api.mcp_server import mcp
from api.store import get_store
from api.seed import seed_plan
from mcp.shared.memory import create_connected_server_and_client_session

EXPECTED_TOOLS = {
    "get_plan",
    "add_task",
    "update_task",
    "delete_task",
    "set_dependencies",
    "reassign_tasks",
    "shift_tasks",
}


@pytest.fixture(autouse=True)
def _reset_store():
    # Ensure each test starts from a known, freshly-seeded plan regardless
    # of state left behind by other test modules sharing the singleton.
    store = get_store()
    store.save_plan(seed_plan())
    yield


@pytest.mark.anyio
async def test_handshake_lists_expected_tools():
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.list_tools()
        names = {t.name for t in result.tools}
        assert EXPECTED_TOOLS <= names


@pytest.mark.anyio
async def test_call_tool_reassign_tasks_succeeds():
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool(
            "reassign_tasks",
            {"from_assignee": "Мария", "to_assignee": "Пётр"},
        )
        assert result.isError is not True
        assert result.content, "expected non-empty tool result content"
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert "OK" in text


@pytest.mark.anyio
async def test_call_tool_reports_tool_error_without_crashing():
    async with create_connected_server_and_client_session(mcp) as client:
        # update_task raises ToolError for an unknown id (unlike delete_task,
        # which is a no-op for unknown ids) - a good case to exercise the
        # ToolError -> text-result path without the MCP call itself failing.
        result = await client.call_tool("update_task", {"id": "does-not-exist", "name": "x"})
        # ToolError is caught inside the tool and returned as text, so the
        # MCP call itself must not be marked as a protocol-level error.
        assert result.isError is not True
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert "Ошибка" in text
        assert "не найдена" in text


@pytest.fixture
def anyio_backend():
    return "asyncio"
