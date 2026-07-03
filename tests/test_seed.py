from api.seed import seed_plan
from api.scheduler import compute_schedule


def test_seed_is_valid_and_schedules():
    plan = seed_plan()
    assert len(plan.tasks) == 7
    assignees = {t.assignee for t in plan.tasks}
    assert len(assignees) >= 4
    sched = compute_schedule(plan)  # must not raise (no cycles)
    assert len(sched) == len(plan.tasks)
