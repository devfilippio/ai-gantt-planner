from api.tool_registry import TOOL_SCHEMAS, dispatch
from api.seed import seed_plan


def test_schemas_are_openai_shaped():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert {"add_task", "update_task", "delete_task", "set_dependencies",
            "reassign_tasks", "shift_tasks", "get_plan"} <= names


def test_dispatch_runs_a_tool():
    plan = seed_plan()
    patch = dispatch("reassign_tasks", {"from_assignee": "Мария", "to_assignee": "Пётр"}, plan)
    assert patch.plan is not None
