from __future__ import annotations

import re
from datetime import date

from api.models import Plan, PlanPatch, Task
from api.scheduler import CycleError, compute_schedule


class ToolError(ValueError):
    pass


def _validate(plan: Plan) -> None:
    ids = {t.id for t in plan.tasks}
    for t in plan.tasks:
        for p in t.predecessors:
            if p not in ids:
                raise ToolError(f"Задача '{t.name}' ссылается на несуществующего предшественника '{p}'")
        if t.id in t.predecessors:
            raise ToolError(f"Задача '{t.name}' не может зависеть от себя")
    try:
        compute_schedule(plan)
    except CycleError as e:
        raise ToolError("Обнаружен цикл зависимостей: " + " -> ".join(e.cycle))


def _patch(plan: Plan, changed: list[str]) -> PlanPatch:
    _validate(plan)
    return PlanPatch(plan=plan, changed_ids=changed)


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "task"
    slug, i = base, 1
    while slug in taken:
        i += 1
        slug = f"{base}-{i}"
    return slug


def _natural_start(plan: Plan, *, predecessors: list[str], exclude_id: str | None = None) -> date:
    """The date a task would start on with lead_days=0: the max end date of
    its predecessors, or project_start if it has none. Computed by scheduling
    the plan as-is (optionally excluding a task, e.g. the one being updated,
    so its own current lead_days/duration don't influence its predecessors'
    dates — though in practice a task never depends on itself)."""
    tasks = plan.tasks
    if exclude_id is not None:
        tasks = [t for t in tasks if t.id != exclude_id]
    probe_plan = Plan(tasks=tasks, project_start=plan.project_start)
    project_start = date.fromisoformat(plan.project_start)
    if not predecessors:
        return project_start
    try:
        sched = {s.id: s for s in compute_schedule(probe_plan)}
    except CycleError:
        return project_start
    ends = [date.fromisoformat(sched[p].end) for p in predecessors if p in sched]
    if not ends:
        return project_start
    return max(ends)


def _lead_days_for_start_date(plan: Plan, *, predecessors: list[str], start_date: str,
                               exclude_id: str | None = None) -> int:
    natural = _natural_start(plan, predecessors=predecessors, exclude_id=exclude_id)
    requested = date.fromisoformat(start_date)
    return max(0, (requested - natural).days)


def add_task(plan: Plan, *, name: str, description: str, assignee: str,
             duration_days: int, predecessors: list[str],
             start_date: str | None = None, lead_days: int | None = None) -> PlanPatch:
    taken = {t.id for t in plan.tasks}
    tid = _slug(name, taken)
    if start_date is not None:
        resolved_lead = _lead_days_for_start_date(plan, predecessors=predecessors, start_date=start_date)
    elif lead_days is not None:
        resolved_lead = lead_days
    else:
        resolved_lead = 0
    new = Task(id=tid, name=name, description=description, assignee=assignee,
               duration_days=duration_days, predecessors=predecessors, lead_days=resolved_lead)
    return _patch(Plan(tasks=[*plan.tasks, new], project_start=plan.project_start), [tid])


def update_task(plan: Plan, *, id: str, start_date: str | None = None, **fields) -> PlanPatch:
    tasks, found = [], False
    for t in plan.tasks:
        if t.id == id:
            found = True
            update = {k: v for k, v in fields.items() if v is not None}
            if start_date is not None:
                predecessors = update.get("predecessors", t.predecessors)
                update["lead_days"] = _lead_days_for_start_date(
                    plan, predecessors=predecessors, start_date=start_date, exclude_id=id,
                )
            elif "predecessors" in update and "lead_days" not in update:
                # Re-linking a task changes its scheduling baseline, so a
                # lead_days computed against the OLD baseline is stale — e.g.
                # a task pinned to May 11 via "+6 days from project start"
                # must not silently become "pred end + 6 days" after linking.
                # "Свяжи A с B" means pure dependency scheduling: start right
                # after the predecessor unless a new date is stated.
                update["lead_days"] = 0
            t = t.model_copy(update=update)
        tasks.append(t)
    if not found:
        raise ToolError(f"Задача '{id}' не найдена")
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), [id])


def delete_task(plan: Plan, *, id: str) -> PlanPatch:
    tasks = [
        t.model_copy(update={"predecessors": [p for p in t.predecessors if p != id]})
        for t in plan.tasks if t.id != id
    ]
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), [])


def set_dependencies(plan: Plan, *, id: str, predecessors: list[str]) -> PlanPatch:
    return update_task(plan, id=id, predecessors=predecessors)


def reassign_tasks(plan: Plan, *, from_assignee: str, to_assignee: str) -> PlanPatch:
    changed, tasks = [], []
    for t in plan.tasks:
        if t.assignee == from_assignee:
            t = t.model_copy(update={"assignee": to_assignee})
            changed.append(t.id)
        tasks.append(t)
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), changed)


def shift_tasks(plan: Plan, *, assignee: str, days: int) -> PlanPatch:
    """True shift: moves an assignee's tasks later (or earlier, for negative
    `days`) by adjusting `lead_days`, leaving `duration_days` — and therefore
    effort — untouched. Negative `days` reduces lead_days, clamped at 0 (a
    task can't start before the later of its predecessors' end / project
    start)."""
    changed, tasks = [], []
    for t in plan.tasks:
        if t.assignee == assignee:
            t = t.model_copy(update={"lead_days": max(0, t.lead_days + days)})
            changed.append(t.id)
        tasks.append(t)
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), changed)
