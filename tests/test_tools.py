import pytest
from api.models import Task, Plan
from api.tools import (
    add_task, update_task, delete_task, set_dependencies,
    reassign_tasks, shift_tasks, ToolError,
)


def _plan():
    return Plan(tasks=[
        Task(id="a", name="A", assignee="Ivan", duration_days=3, predecessors=[]),
        Task(id="b", name="B", assignee="Ivan", duration_days=2, predecessors=["a"]),
        Task(id="c", name="C", assignee="Oleg", duration_days=4, predecessors=["a"]),
    ], project_start="2026-05-05")


def test_add_task_appends_and_reports_change():
    patch = add_task(_plan(), name="D", description="", assignee="Anna", duration_days=2, predecessors=["b"])
    ids = {t.id for t in patch.plan.tasks}
    assert len(ids) == 4
    new_id = next(t.id for t in patch.plan.tasks if t.name == "D")
    assert patch.changed_ids == [new_id]


def test_update_task_changes_field():
    patch = update_task(_plan(), id="a", duration_days=10)
    assert next(t for t in patch.plan.tasks if t.id == "a").duration_days == 10
    assert patch.changed_ids == ["a"]


def test_delete_task_removes_and_cleans_predecessors():
    patch = delete_task(_plan(), id="a")
    ids = {t.id for t in patch.plan.tasks}
    assert "a" not in ids
    assert all("a" not in t.predecessors for t in patch.plan.tasks)


def test_reassign_tasks_bulk():
    patch = reassign_tasks(_plan(), from_assignee="Ivan", to_assignee="Petrov")
    assert {t.id for t in patch.plan.tasks if t.assignee == "Petrov"} == {"a", "b"}
    assert set(patch.changed_ids) == {"a", "b"}


def test_shift_tasks_increases_duration_of_gate():
    # shifting by assignee moves their tasks later by inserting slack via duration on a lead task is out of scope;
    # shift = add N days to duration of matched tasks' start via a lead-in. Here we shift Oleg's tasks by 7 days.
    patch = shift_tasks(_plan(), assignee="Oleg", days=7)
    assert set(patch.changed_ids) == {"c"}


def test_set_dependencies_rejecting_cycle_raises():
    with pytest.raises(ToolError):
        set_dependencies(_plan(), id="a", predecessors=["b"])  # a<-b<-a cycle
