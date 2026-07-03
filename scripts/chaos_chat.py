"""Chaos harness: runs a battery of arbitrary/adversarial chat commands through
the REAL agent loop (run_agent_turn + OpenRouterLLM) against a FRESH seed plan
each time, and reports what actually happened — tool calls, final message,
errors, and a plan diff summary.

Purpose: the mission is "any input the client types must produce a sensible
outcome." This script is how we observe the real model's behavior (not
MockLLM) without hitting the deployed prod app, so we can catch hallucinated
changes, silent no-ops, infinite loops, or crashes before they reach a user.

Run (requires OPENROUTER_API_KEY loaded, e.g. `set -a && . ./.env && set +a`):
    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/chaos_chat.py

Optionally pass indices to run a subset (1-based, matching the battery table
below), e.g.:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/chaos_chat.py 5 13 17
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.agent import OpenRouterLLM, run_agent_turn
from api.scheduler import compute_schedule
from api.seed import seed_plan


@dataclass
class Command:
    label: str
    message: str
    history: list[dict] = field(default_factory=list)


BATTERY: list[Command] = [
    Command("1. vague/no-op", "сделай план красивее"),
    Command("2. off-domain", "какая погода в Москве?"),
    Command("3. destructive bulk delete", "удали все задачи"),
    Command("4. partial name delete", "удали задачу дизайн"),
    Command("5. nonexistent assignee", "перенеси задачи Пети на неделю"),
    Command("6. bulk shift ALL assignees", "увеличь все задачи на 2 дня"),
    Command("7. swap assignees", "поменяй местами исполнителей у QA и дизайна"),
    Command("8. English update", "make QA 10 days long"),
    Command("9. duration question", "сколько дней займёт весь проект?"),
    Command("10. analytics question", "кто самый загруженный?"),
    Command("11. missing everything (add)", "добавь задачу"),
    Command("12. gibberish", "щавыфщцуа"),
    Command("13. cycle request", "сделай так чтобы дизайн зависел от qa а qa от дизайна"),
    Command("14. far future date", "перенеси запуск на 1 августа"),
    Command("15. goal-level request", "сократи проект на неделю"),
    Command("16. broken English add", "Milk buy for Maria tomorrow"),
    Command("17. undo via words", "отмени последнее изменение"),
    Command("18. bulk add", "добавь 5 задач тестирования по одному дню"),
]


def _plan_summary(plan) -> dict:
    try:
        schedule = {s.id: s for s in compute_schedule(plan)}
        project_end = max((s.end for s in schedule.values()), default=None)
    except Exception:
        project_end = None
    return {
        "task_count": len(plan.tasks),
        "assignees": sorted({t.assignee for t in plan.tasks}),
        "durations": {t.id: t.duration_days for t in plan.tasks},
        "project_end": project_end,
    }


def _diff_summary(before, after) -> str:
    b = _plan_summary(before)
    a = _plan_summary(after)
    parts = []
    if a["task_count"] != b["task_count"]:
        parts.append(f"task_count {b['task_count']}->{a['task_count']}")
    changed_durations = {
        tid: (b["durations"].get(tid), dur)
        for tid, dur in a["durations"].items()
        if b["durations"].get(tid) != dur
    }
    if changed_durations:
        parts.append(f"duration changes: {changed_durations}")
    if b["assignees"] != a["assignees"]:
        parts.append(f"assignees {b['assignees']}->{a['assignees']}")
    if b["project_end"] != a["project_end"]:
        parts.append(f"project_end {b['project_end']}->{a['project_end']}")
    return "; ".join(parts) if parts else "(no visible plan change)"


def run_one(cmd: Command) -> dict:
    plan = seed_plan()
    before = plan
    llm = OpenRouterLLM()

    tool_calls = []
    final_message = ""
    errors = []
    event_count = 0
    saw_done = False

    try:
        for event in run_agent_turn(cmd.message, plan, llm, history=cmd.history):
            event_count += 1
            etype = event["type"]
            if etype == "tool_call":
                tool_calls.append({"tool": event["tool"], "args": event["args"]})
            elif etype == "patch":
                plan = _plan_from_patch(event["plan_patch"])
            elif etype == "message":
                final_message = event["text"]
            elif etype == "error":
                errors.append(event["detail"])
            elif etype == "done":
                saw_done = True
    except Exception as e:  # crash guard - report, don't blow up the whole battery
        errors.append(f"EXCEPTION: {type(e).__name__}: {e}")

    return {
        "label": cmd.label,
        "message": cmd.message,
        "tool_calls": tool_calls,
        "final_message": final_message,
        "errors": errors,
        "event_count": event_count,
        "saw_done": saw_done,
        "diff": _diff_summary(before, plan),
    }


def _plan_from_patch(plan_patch: dict):
    from api.models import Plan

    return Plan.model_validate(plan_patch["plan"])


def main() -> None:
    indices = [int(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else None
    battery = BATTERY
    if indices:
        battery = [c for c in BATTERY if int(c.label.split(".")[0]) in indices]

    for cmd in battery:
        result = run_one(cmd)
        print("=" * 100)
        print(f"[{result['label']}] \"{result['message']}\"")
        print(f"  tool_calls ({len(result['tool_calls'])}):")
        for tc in result["tool_calls"]:
            print(f"    - {tc['tool']}({tc['args']})")
        print(f"  final_message: {result['final_message']!r}")
        if result["errors"]:
            print(f"  errors: {result['errors']}")
        print(f"  events: {result['event_count']}, done: {result['saw_done']}")
        print(f"  plan diff: {result['diff']}")


if __name__ == "__main__":
    main()
