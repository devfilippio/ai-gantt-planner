from api.store import MemoryStore
from api.seed import seed_plan


def test_store_saves_and_loads():
    s = MemoryStore()
    s.reset_to_seed()
    plan = s.get_plan()
    assert len(plan.tasks) >= 20


def test_store_snapshot_and_undo():
    s = MemoryStore()
    s.reset_to_seed()
    before = len(s.get_plan().tasks)
    s.snapshot()
    p = s.get_plan()
    p.tasks = p.tasks[:-1]
    s.save_plan(p)
    assert len(s.get_plan().tasks) == before - 1
    s.undo()
    assert len(s.get_plan().tasks) == before
