"""Real MCP server for the plan mutation tools, using the `mcp` SDK's
streamable-HTTP transport (mcp>=1.9), mounted stateless inside the FastAPI
app (correct mode for a serverless/Vercel deployment: no server-side
session affinity is required between requests).

Each MCP tool below:
  1. loads the current plan from the shared store (`get_store().get_plan()`),
  2. calls the corresponding `api/tools.py` function via `dispatch`,
  3. on success, persists the resulting plan (`store.save_plan(patch.plan)`)
     and returns a concise summary (changed task ids + total task count),
  4. on `ToolError`, returns the error message as tool text instead of
     raising, so a bad LLM-driven call surfaces as a normal tool result
     rather than crashing the MCP session.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from api.store import get_store
from api.tool_registry import dispatch
from api.tools import ToolError

# stateless_http=True: no session state is kept across requests, which is
# required for a serverless deployment (Vercel functions are not guaranteed
# to route two requests from the same "session" to the same instance).
# streamable_http_path="/" so that mounting this app at /api/mcp in the
# parent FastAPI app exposes the MCP endpoint at exactly /api/mcp (instead
# of the SDK's default /api/mcp/mcp).
# The MCP transport runs behind Vercel's edge (which already validates the
# real Host), so the SDK's built-in DNS-rebinding Host/Origin check would
# otherwise reject the rewritten internal request with 421 "Invalid Host
# header". Disable it for this serverless, stateless deployment.
mcp = FastMCP(
    "ai-gantt-planner",
    stateless_http=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


def _run(_tool_name: str, **args) -> str:
    """Shared execution path for all mutating tools: dispatch to
    api.tool_registry.dispatch, persist on success, and turn ToolError into
    plain text instead of an exception."""
    store = get_store()
    plan = store.get_plan()
    try:
        patch = dispatch(_tool_name, args, plan)
    except ToolError as e:
        return f"Ошибка: {e}"
    store.save_plan(patch.plan)
    return (
        f"OK: {_tool_name} применён. "
        f"Изменённые задачи: {patch.changed_ids or '[]'}. "
        f"Всего задач в плане: {len(patch.plan.tasks)}."
    )


@mcp.tool()
def get_plan() -> str:
    """Возвращает текущий план проекта без изменений."""
    store = get_store()
    plan = store.get_plan()
    return plan.model_dump_json()


@mcp.tool()
def add_task(
    name: str,
    description: str,
    assignee: str,
    duration_days: int,
    predecessors: list[str],
) -> str:
    """Добавляет новую задачу в план проекта."""
    return _run(
        "add_task",
        name=name,
        description=description,
        assignee=assignee,
        duration_days=duration_days,
        predecessors=predecessors,
    )


@mcp.tool()
def update_task(
    id: str,
    name: str | None = None,
    description: str | None = None,
    assignee: str | None = None,
    duration_days: int | None = None,
    predecessors: list[str] | None = None,
) -> str:
    """Обновляет поля существующей задачи (только переданные поля изменяются)."""
    return _run(
        "update_task",
        id=id,
        name=name,
        description=description,
        assignee=assignee,
        duration_days=duration_days,
        predecessors=predecessors,
    )


@mcp.tool()
def delete_task(id: str) -> str:
    """Удаляет задачу из плана и очищает ссылки на неё в предшественниках других задач."""
    return _run("delete_task", id=id)


@mcp.tool()
def set_dependencies(id: str, predecessors: list[str]) -> str:
    """Задаёт полный список предшественников для указанной задачи."""
    return _run("set_dependencies", id=id, predecessors=predecessors)


@mcp.tool()
def reassign_tasks(from_assignee: str, to_assignee: str) -> str:
    """Массово переназначает все задачи одного ответственного на другого."""
    return _run("reassign_tasks", from_assignee=from_assignee, to_assignee=to_assignee)


@mcp.tool()
def shift_tasks(assignee: str, days: int) -> str:
    """Сдвигает задачи указанного ответственного, увеличивая их длительность на заданное число дней."""
    return _run("shift_tasks", assignee=assignee, days=days)


# ASGI sub-application to mount at /api/mcp in the parent FastAPI app.
mcp_app = mcp.streamable_http_app()
