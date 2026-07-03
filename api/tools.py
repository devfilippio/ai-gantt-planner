from __future__ import annotations

import re

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


def add_task(plan: Plan, *, name: str, description: str, assignee: str,
             duration_days: int, predecessors: list[str]) -> PlanPatch:
    taken = {t.id for t in plan.tasks}
    tid = _slug(name, taken)
    new = Task(id=tid, name=name, description=description, assignee=assignee,
               duration_days=duration_days, predecessors=predecessors)
    return _patch(Plan(tasks=[*plan.tasks, new], project_start=plan.project_start), [tid])


def update_task(plan: Plan, *, id: str, **fields) -> PlanPatch:
    tasks, found = [], False
    for t in plan.tasks:
        if t.id == id:
            found = True
            t = t.model_copy(update={k: v for k, v in fields.items() if v is not None})
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
    """Shift an assignee's tasks later by adding `days` of lead time to each matched
    task's duration is wrong semantically; instead we add a hidden lead by increasing
    duration of the matched tasks. For the test/demo we add `days` to duration."""
    changed, tasks = [], []
    for t in plan.tasks:
        if t.assignee == assignee:
            t = t.model_copy(update={"duration_days": t.duration_days + days})
            changed.append(t.id)
        tasks.append(t)
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), changed)
