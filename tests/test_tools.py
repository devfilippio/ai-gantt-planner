import pytest
from api.models import Task, Plan
from api.scheduler import compute_schedule
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


def test_shift_tasks_is_true_shift_keeps_duration_moves_start():
    """shift_tasks must be a true shift: duration stays constant, only the
    start (via lead_days) moves later. Previously this bumped duration_days,
    which silently changed the task's effort — see docs/roadmap-to-production.md."""
    plan = _plan()
    before_sched = {s.id: s for s in compute_schedule(plan)}
    patch = shift_tasks(plan, assignee="Oleg", days=7)
    assert set(patch.changed_ids) == {"c"}

    shifted = next(t for t in patch.plan.tasks if t.id == "c")
    original = next(t for t in plan.tasks if t.id == "c")
    assert shifted.duration_days == original.duration_days  # duration unchanged

    after_sched = {s.id: s for s in compute_schedule(patch.plan)}
    from datetime import date, timedelta
    expected_start = date.fromisoformat(before_sched["c"].start) + timedelta(days=7)
    assert after_sched["c"].start == expected_start.isoformat()
    # duration is the same, so the gap between start and end is unchanged.
    expected_end = date.fromisoformat(before_sched["c"].end) + timedelta(days=7)
    assert after_sched["c"].end == expected_end.isoformat()


def test_shift_tasks_negative_days_moves_earlier_clamped_at_zero():
    plan = _plan()
    # c already has lead_days=0; shifting earlier should clamp at 0, not go negative.
    patch = shift_tasks(plan, assignee="Oleg", days=-3)
    shifted = next(t for t in patch.plan.tasks if t.id == "c")
    assert shifted.lead_days == 0

    # Now shift later first, then earlier by less than the accumulated lead —
    # should reduce lead_days rather than clamp.
    patch2 = shift_tasks(patch.plan, assignee="Oleg", days=5)
    shifted2 = next(t for t in patch2.plan.tasks if t.id == "c")
    assert shifted2.lead_days == 5
    patch3 = shift_tasks(patch2.plan, assignee="Oleg", days=-2)
    shifted3 = next(t for t in patch3.plan.tasks if t.id == "c")
    assert shifted3.lead_days == 3


def test_set_dependencies_rejecting_cycle_raises():
    with pytest.raises(ToolError):
        set_dependencies(_plan(), id="a", predecessors=["b"])  # a<-b<-a cycle


def test_add_task_with_start_date_sets_lead_days_for_independent_task():
    plan = _plan()  # project_start 2026-05-05
    patch = add_task(
        plan, name="Купить молоко", description="", assignee="Мария",
        duration_days=7, predecessors=[], start_date="2026-05-11",
    )
    new = next(t for t in patch.plan.tasks if t.name == "Купить молоко")
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched[new.id].start == "2026-05-11"


def test_add_task_with_start_date_and_predecessor():
    plan = _plan()
    sched_before = {s.id: s for s in compute_schedule(plan)}
    # a ends 2026-05-08. Ask for a start 2 days after that.
    from datetime import date, timedelta
    natural_start = date.fromisoformat(sched_before["a"].end)
    requested = (natural_start + timedelta(days=2)).isoformat()
    patch = add_task(
        plan, name="D", description="", assignee="Anna",
        duration_days=2, predecessors=["a"], start_date=requested,
    )
    new = next(t for t in patch.plan.tasks if t.name == "D")
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched[new.id].start == requested


def test_add_task_with_explicit_lead_days():
    patch = add_task(
        _plan(), name="E", description="", assignee="Anna",
        duration_days=1, predecessors=[], lead_days=6,
    )
    new = next(t for t in patch.plan.tasks if t.name == "E")
    assert new.lead_days == 6
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched[new.id].start == "2026-05-11"


def test_add_task_start_date_wins_over_lead_days_when_both_given():
    patch = add_task(
        _plan(), name="F", description="", assignee="Anna",
        duration_days=1, predecessors=[], lead_days=99, start_date="2026-05-11",
    )
    new = next(t for t in patch.plan.tasks if t.name == "F")
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched[new.id].start == "2026-05-11"


def test_update_task_start_date_recomputes_lead_against_natural_start():
    plan = _plan()
    # task "b" depends on "a" (ends 2026-05-08). Ask to move b's start to 2026-05-15.
    patch = update_task(plan, id="b", start_date="2026-05-15")
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched["b"].start == "2026-05-15"


def test_update_task_lead_days_direct():
    patch = update_task(_plan(), id="a", lead_days=4)
    updated = next(t for t in patch.plan.tasks if t.id == "a")
    assert updated.lead_days == 4
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched["a"].start == "2026-05-09"


def test_set_dependencies_resets_stale_lead_days():
    """Owner-reported bug: a task pinned to a calendar date (lead_days from
    project start) silently kept that offset after being linked to a
    predecessor, drifting to 'pred end + old offset'. Linking must reschedule
    purely by the dependency: start right after the predecessor ends."""
    from datetime import date, timedelta
    from api.seed import seed_plan
    from api.scheduler import compute_schedule

    plan = seed_plan()
    # "Купить молоко" starting 6 days after project_start (the seed's
    # dynamic project_start, not a fixed calendar date).
    ps = date.fromisoformat(plan.project_start)
    target = (ps + timedelta(days=6)).isoformat()
    patch = add_task(plan, name="Купить молоко", description="", assignee="Мария",
                     duration_days=7, predecessors=[], start_date=target)
    milk_id = patch.changed_ids[0]
    sched = {s.id: s for s in compute_schedule(patch.plan)}
    assert sched[milk_id].start == target

    # «свяжи с дизайном» — без новой даты
    linked = set_dependencies(patch.plan, id=milk_id, predecessors=["design"])
    sched2 = {s.id: s for s in compute_schedule(linked.plan)}
    design_end = sched2["design"].end
    assert sched2[milk_id].start == design_end, (
        f"linked task must start right after its predecessor ({design_end}), "
        f"got {sched2[milk_id].start}"
    )


def test_update_with_start_date_and_predecessors_keeps_requested_date():
    """Counter-case: when the user DOES state a date while linking, honour it."""
    from datetime import date, timedelta
    from api.seed import seed_plan
    from api.scheduler import compute_schedule

    plan = seed_plan()
    ps = date.fromisoformat(plan.project_start)
    target = (ps + timedelta(days=6)).isoformat()
    later_target = (ps + timedelta(days=15)).isoformat()
    patch = add_task(plan, name="Купить молоко", description="", assignee="Мария",
                     duration_days=7, predecessors=[], start_date=target)
    milk_id = patch.changed_ids[0]
    moved = update_task(patch.plan, id=milk_id, predecessors=["design"],
                        start_date=later_target)
    sched = {s.id: s for s in compute_schedule(moved.plan)}
    assert sched[milk_id].start == later_target


def test_shift_all_tasks_moves_whole_plan_by_exactly_n_days():
    """Owner-reported: «передвинь все задачи на 3 дня вперед» had no tool path
    (shift_tasks required an assignee) and the agent improvised inconsistently.
    Now assignee is optional: without it the WHOLE plan shifts — every task's
    start moves by exactly N days (dependents don't accumulate 2N/3N), and
    durations stay untouched."""
    from api.seed import seed_plan
    from api.scheduler import compute_schedule

    plan = seed_plan()
    before = {s.id: s for s in compute_schedule(plan)}
    durations_before = {t.id: t.duration_days for t in plan.tasks}

    patch = shift_tasks(plan, days=3)

    after = {s.id: s for s in compute_schedule(patch.plan)}
    from datetime import date
    for tid, b in before.items():
        delta = (date.fromisoformat(after[tid].start) - date.fromisoformat(b.start)).days
        assert delta == 3, f"{tid}: start moved by {delta}, expected exactly 3"
    assert {t.id: t.duration_days for t in patch.plan.tasks} == durations_before
    # every bar should light up on screen
    assert set(patch.changed_ids) == {t.id for t in plan.tasks}
