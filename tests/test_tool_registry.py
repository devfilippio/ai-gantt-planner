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


def test_dispatch_add_task_passes_through_start_date():
    plan = seed_plan()
    patch = dispatch(
        "add_task",
        {"name": "Купить молоко", "description": "", "assignee": "Мария",
         "duration_days": 7, "predecessors": [], "start_date": "2026-05-11"},
        plan,
    )
    new = next(t for t in patch.plan.tasks if t.name == "Купить молоко")
    from api.scheduler import compute_schedule
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched[new.id].start == "2026-05-11"
