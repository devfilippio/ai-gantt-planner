"""Seed data: a compact landing page launch plan ("Запуск лендинга").

Kept deliberately small (7 tasks, 4 assignees) so the Gantt chart reads
cleanly at a glance. Two join points (`frontend`, `qa`) each have two
predecessors, giving a real critical path plus a couple of parallel
branches (`design`/`backend` off `research`; `frontend`/`content` off
`design`) rather than a single linear chain.
"""
from __future__ import annotations

from api.models import Plan, Task

_ASSIGNEES = ["Мария", "Иван", "Олег", "Анна"]


def seed_plan() -> Plan:
    tasks = [
        Task(
            id="research",
            name="Исследование и бриф",
            description="Сбор требований, анализ конкурентов, подготовка брифа на лендинг",
            assignee="Мария",
            duration_days=4,
            predecessors=[],
        ),
        Task(
            id="design",
            name="Дизайн лендинга",
            description="Визуальная концепция и макеты ключевых экранов",
            assignee="Анна",
            duration_days=5,
            predecessors=["research"],
        ),
        Task(
            id="backend",
            name="Backend и форма заявки",
            description="API приёма заявок, интеграция с CRM",
            assignee="Иван",
            duration_days=6,
            predecessors=["research"],
        ),
        Task(
            id="content",
            name="Тексты и контент",
            description="Подготовка текстов, изображений и SEO-разметки по макетам",
            assignee="Мария",
            duration_days=4,
            predecessors=["design"],
        ),
        Task(
            id="frontend",
            name="Вёрстка и интеграция",
            description="Вёрстка страницы по дизайну и подключение к backend-API",
            assignee="Олег",
            duration_days=6,
            predecessors=["design", "backend"],
        ),
        Task(
            id="qa",
            name="QA и тестирование",
            description="Функциональное и кроссбраузерное тестирование перед запуском",
            assignee="Олег",
            duration_days=4,
            predecessors=["frontend", "content"],
        ),
        Task(
            id="launch",
            name="Запуск и мониторинг",
            description="Публикация лендинга и мониторинг метрик после запуска",
            assignee="Анна",
            duration_days=3,
            predecessors=["qa"],
        ),
    ]
    return Plan(tasks=tasks, project_start="2026-05-05")
