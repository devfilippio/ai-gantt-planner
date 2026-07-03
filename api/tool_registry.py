from __future__ import annotations

from api.models import Plan, PlanPatch
from api.tools import (
    ToolError,
    add_task,
    delete_task,
    reassign_tasks,
    set_dependencies,
    shift_tasks,
    update_task,
)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Добавляет новую задачу в план проекта.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название задачи"},
                    "description": {"type": "string", "description": "Описание задачи"},
                    "assignee": {"type": "string", "description": "Ответственный за задачу"},
                    "duration_days": {"type": "integer", "description": "Длительность задачи в днях"},
                    "predecessors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список id (или точных названий) задач-предшественников",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Дата начала YYYY-MM-DD — для независимой задачи или отложенного старта. "
                                        "Если указана, имеет приоритет над lead_days.",
                    },
                    "lead_days": {
                        "type": "integer",
                        "description": "Сколько дополнительных календарных дней подождать перед стартом "
                                        "(после того как освободятся предшественники или наступит старт проекта). "
                                        "Обычно проще указать start_date.",
                    },
                },
                "required": ["name", "description", "assignee", "duration_days", "predecessors"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Обновляет поля существующей задачи (только переданные поля изменяются).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Id задачи (или её точное название)"},
                    "name": {"type": "string", "description": "Новое название задачи"},
                    "description": {"type": "string", "description": "Новое описание задачи"},
                    "assignee": {"type": "string", "description": "Новый ответственный за задачу"},
                    "duration_days": {"type": "integer", "description": "Новая длительность задачи в днях"},
                    "predecessors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Новый список id (или точных названий) задач-предшественников",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Новая дата начала YYYY-MM-DD — задаёт lead_days так, чтобы задача "
                                        "стартовала именно в эту дату (относительно предшественников или "
                                        "старта проекта).",
                    },
                    "lead_days": {
                        "type": "integer",
                        "description": "Новое число дополнительных дней ожидания перед стартом задачи. "
                                        "Обычно проще указать start_date.",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Удаляет задачу из плана и очищает ссылки на неё в предшественниках других задач.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Id задачи (или её точное название)"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_dependencies",
            "description": "Задаёт полный список предшественников для указанной задачи.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Id задачи (или её точное название)"},
                    "predecessors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список id (или точных названий) задач-предшественников",
                    },
                },
                "required": ["id", "predecessors"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reassign_tasks",
            "description": "Массово переназначает все задачи одного ответственного на другого.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_assignee": {"type": "string", "description": "Текущий ответственный"},
                    "to_assignee": {"type": "string", "description": "Новый ответственный"},
                },
                "required": ["from_assignee", "to_assignee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shift_tasks",
            "description": "Сдвигает начало задач ответственного на N дней (длительность не меняется); "
                            "отрицательное N — раньше.",
            "parameters": {
                "type": "object",
                "properties": {
                    "assignee": {"type": "string", "description": "Ответственный, чьи задачи нужно сдвинуть"},
                    "days": {
                        "type": "integer",
                        "description": "Число дней сдвига начала задач; отрицательное значение сдвигает раньше",
                    },
                },
                "required": ["assignee", "days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan",
            "description": "Возвращает текущий план проекта без изменений.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last_turn",
            "description": "Откатывает план к состоянию до последнего применённого агентом изменения "
                            "(отменяет последнюю мутацию плана). Без аргументов.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

_DISPATCH_TABLE = {
    "add_task": add_task,
    "update_task": update_task,
    "delete_task": delete_task,
    "set_dependencies": set_dependencies,
    "reassign_tasks": reassign_tasks,
    "shift_tasks": shift_tasks,
}

# Args each tool actually accepts — anything else the model invents is dropped
# instead of raising TypeError deep inside the tool function.
_KNOWN_ARGS = {
    "add_task": {"name", "description", "assignee", "duration_days", "predecessors",
                 "start_date", "lead_days"},
    "update_task": {"id", "name", "description", "assignee", "duration_days", "predecessors",
                     "start_date", "lead_days"},
    "delete_task": {"id"},
    "set_dependencies": {"id", "predecessors"},
    "reassign_tasks": {"from_assignee", "to_assignee"},
    "shift_tasks": {"assignee", "days"},
}


def _resolve_task_ref(ref: str, plan: Plan) -> str:
    """Resolve a task reference that may be an id OR a human name.

    LLMs frequently pass the visible task name ("Вёрстка и интеграция") where
    the schema asks for an id ("frontend"). Exact id match wins; otherwise fall
    back to a case-insensitive name match. Unresolvable refs are returned
    as-is so the tool's own validation produces its normal error message.
    """
    ids = {t.id for t in plan.tasks}
    if ref in ids:
        return ref
    needle = ref.strip().lower()
    for t in plan.tasks:
        if t.name.strip().lower() == needle:
            return t.id
    # Forgiving partial match — unique substring of a name (e.g. "вёрстка").
    partial = [t.id for t in plan.tasks if needle and needle in t.name.strip().lower()]
    if len(partial) == 1:
        return partial[0]
    return ref


def _normalize_args(name: str, args: dict, plan: Plan) -> dict:
    known = _KNOWN_ARGS.get(name, set())
    out = {k: v for k, v in args.items() if k in known}
    if isinstance(out.get("id"), str):
        out["id"] = _resolve_task_ref(out["id"], plan)
    preds = out.get("predecessors")
    if isinstance(preds, list):
        out["predecessors"] = [
            _resolve_task_ref(p, plan) if isinstance(p, str) else p for p in preds
        ]
    return out


def dispatch(name: str, args: dict, plan: Plan) -> PlanPatch:
    if name == "get_plan":
        return PlanPatch(plan=plan, changed_ids=[])
    func = _DISPATCH_TABLE.get(name)
    if func is None:
        raise ToolError(f"Неизвестный инструмент: '{name}'")
    return func(plan, **_normalize_args(name, args, plan))
