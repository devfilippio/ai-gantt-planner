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
                        "description": "Список id задач-предшественников",
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
                    "id": {"type": "string", "description": "Id задачи, которую нужно обновить"},
                    "name": {"type": "string", "description": "Новое название задачи"},
                    "description": {"type": "string", "description": "Новое описание задачи"},
                    "assignee": {"type": "string", "description": "Новый ответственный за задачу"},
                    "duration_days": {"type": "integer", "description": "Новая длительность задачи в днях"},
                    "predecessors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Новый список id задач-предшественников",
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
                    "id": {"type": "string", "description": "Id задачи, которую нужно удалить"},
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
                    "id": {"type": "string", "description": "Id задачи, для которой задаются зависимости"},
                    "predecessors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список id задач-предшественников",
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
            "description": "Сдвигает задачи указанного ответственного, увеличивая их длительность на заданное число дней.",
            "parameters": {
                "type": "object",
                "properties": {
                    "assignee": {"type": "string", "description": "Ответственный, чьи задачи нужно сдвинуть"},
                    "days": {"type": "integer", "description": "Число дней, на которое сдвигаются задачи"},
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
]

_DISPATCH_TABLE = {
    "add_task": add_task,
    "update_task": update_task,
    "delete_task": delete_task,
    "set_dependencies": set_dependencies,
    "reassign_tasks": reassign_tasks,
    "shift_tasks": shift_tasks,
}


def dispatch(name: str, args: dict, plan: Plan) -> PlanPatch:
    if name == "get_plan":
        return PlanPatch(plan=plan, changed_ids=[])
    func = _DISPATCH_TABLE.get(name)
    if func is None:
        raise ToolError(f"Неизвестный инструмент: '{name}'")
    return func(plan, **args)
