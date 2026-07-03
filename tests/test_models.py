from api.models import Task, Plan


def test_task_requires_positive_duration():
    import pytest
    with pytest.raises(ValueError):
        Task(id="a", name="A", description="", assignee="X", duration_days=0, predecessors=[])


def test_plan_roundtrips_tasks():
    t = Task(id="a", name="A", description="d", assignee="X", duration_days=3, predecessors=[])
    plan = Plan(tasks=[t], project_start="2026-05-05")
    assert plan.tasks[0].duration_days == 3
    assert plan.project_start == "2026-05-05"
