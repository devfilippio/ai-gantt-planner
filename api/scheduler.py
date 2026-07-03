from __future__ import annotations

from datetime import date, timedelta

from api.models import Plan, Scheduled


class CycleError(ValueError):
    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__("Dependency cycle: " + " -> ".join(cycle))


def _topo_order(plan: Plan) -> list[str]:
    ids = {t.id for t in plan.tasks}
    preds = {t.id: [p for p in t.predecessors if p in ids] for t in plan.tasks}
    indeg = {i: 0 for i in ids}
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for tid, ps in preds.items():
        for p in ps:
            adj[p].append(tid)
            indeg[tid] += 1
    queue = [i for i in ids if indeg[i] == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if len(order) != len(ids):
        stuck = [i for i in ids if indeg[i] > 0]
        raise CycleError(stuck)
    return order


def compute_schedule(plan: Plan) -> list[Scheduled]:
    by_id = {t.id: t for t in plan.tasks}
    order = _topo_order(plan)
    start_d = date.fromisoformat(plan.project_start)
    starts: dict[str, date] = {}
    ends: dict[str, date] = {}
    for tid in order:
        t = by_id[tid]
        valid_preds = [p for p in t.predecessors if p in ends]
        s = max((ends[p] for p in valid_preds), default=start_d)
        e = s + timedelta(days=t.duration_days)
        starts[tid], ends[tid] = s, e
    result = [
        Scheduled(id=tid, start=starts[tid].isoformat(), end=ends[tid].isoformat())
        for tid in by_id
    ]
    _mark_critical(plan, starts, ends, result)
    return result


def _mark_critical(plan, starts, ends, result):
    if not ends:
        return
    project_end = max(ends.values())
    by_id = {t.id: t for t in plan.tasks}
    scheduled = {s.id: s for s in result}

    def on_critical(tid: str) -> bool:
        return ends[tid] == project_end or any(
            on_critical(succ.id)
            for succ in plan.tasks
            if tid in succ.predecessors and starts[succ.id] == ends[tid]
        )

    for tid in by_id:
        scheduled[tid].is_critical = on_critical(tid)
