import pytest

from api.models import Task, Plan
from api.scheduler import CycleError, compute_schedule


def _plan(*tasks):
    return Plan(tasks=list(tasks), project_start="2026-05-05")


def test_single_task_starts_at_project_start():
    plan = _plan(Task(id="a", name="A", duration_days=3, predecessors=[]))
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["a"].start == "2026-05-05"
    assert sched["a"].end == "2026-05-08"  # 3 calendar days


def test_successor_starts_after_predecessor_end():
    plan = _plan(
        Task(id="a", name="A", duration_days=3, predecessors=[]),
        Task(id="b", name="B", duration_days=2, predecessors=["a"]),
    )
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["b"].start == "2026-05-08"
    assert sched["b"].end == "2026-05-10"


def test_task_with_two_predecessors_starts_after_latest():
    plan = _plan(
        Task(id="a", name="A", duration_days=3, predecessors=[]),
        Task(id="b", name="B", duration_days=7, predecessors=[]),
        Task(id="c", name="C", duration_days=1, predecessors=["a", "b"]),
    )
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["c"].start == "2026-05-12"  # after B (longer)


def test_cycle_raises_with_offending_ids():
    plan = _plan(
        Task(id="a", name="A", duration_days=1, predecessors=["b"]),
        Task(id="b", name="B", duration_days=1, predecessors=["a"]),
    )
    with pytest.raises(CycleError) as exc:
        compute_schedule(plan)
    assert set(exc.value.cycle) == {"a", "b"}


def test_critical_path_flag():
    plan = _plan(
        Task(id="a", name="A", duration_days=3, predecessors=[]),
        Task(id="b", name="B", duration_days=7, predecessors=[]),
        Task(id="c", name="C", duration_days=1, predecessors=["a", "b"]),
    )
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["c"].is_critical is True
    assert sched["b"].is_critical is True   # longer branch feeds c
    assert sched["a"].is_critical is False  # slack
