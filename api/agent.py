from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Callable, Iterator, Protocol

from api.models import Plan, PlanPatch
from api.scheduler import compute_schedule
from api.tool_registry import TOOL_SCHEMAS, dispatch
from api.tools import ToolError

MAX_TURNS = 8
HISTORY_CAP = 20


def compact_plan(plan: Plan) -> str:
    """A small, LLM-friendly listing of the current plan so the model always
    knows the real task ids (and can resolve a user's "после вёрстки" to the
    right id) without having to loop on get_plan.

    Includes computed start/end dates (via compute_schedule) so the model can
    reason about actual calendar dates - e.g. resolving "с 11 по 18 мая" into
    a start_date/duration pair - not just relative durations in days. Falls
    back to the plain duration-only listing if scheduling fails (e.g. a
    dependency cycle mid-edit), so a broken plan never crashes the chat."""
    if not plan.tasks:
        return "(план пуст)"

    try:
        schedule = {s.id: s for s in compute_schedule(plan)}
        header = (
            f"Старт проекта: {plan.project_start}. "
            f"Сегодня: {date.today().isoformat()}."
        )
        lines = [header]
        for t in plan.tasks:
            preds = ", ".join(t.predecessors) if t.predecessors else "—"
            sched = schedule.get(t.id)
            span = f"{sched.start}→{sched.end}" if sched else "?"
            lines.append(
                f"{t.id} · {t.name} · {t.assignee} · {t.duration_days}д · {span} · преды: {preds}"
            )
        return "\n".join(lines)
    except Exception:
        lines = []
        for t in plan.tasks:
            preds = ", ".join(t.predecessors) if t.predecessors else "—"
            lines.append(
                f"{t.id} · {t.name} · {t.assignee} · {t.duration_days}д · предшественники: {preds}"
            )
        return "\n".join(lines)

SYSTEM_PROMPT = """\
Ты — ассистент по управлению планом проекта (диаграмма Ганта). Владелец плана \
— пользователь: это его план и его задачи, а не корпоративный проект, который \
ты модерируешь.

Главное правило: ЛЮБАЯ задача, которую пользователь просит добавить, легитимна. \
«Купить молоко», «сходить к врачу», «забрать посылку» — валидные задачи плана, \
если пользователь так решил. Никогда не оценивай уместность, важность или \
«проектность» задачи и не отказывайся её добавить по этой причине.

Используй разумные дефолты вместо переспросов:
- Нет описания — оставь пустым.
- Нет предшественников — задача независимая (predecessors: []).
- Названа дата начала («с 11 мая», «начиная с понедельника») — передай её как \
start_date (YYYY-MM-DD).
- Назван диапазон дат («с 11 по 18 мая») — start_date = начало диапазона, \
duration_days = число дней между датами (11→18 мая = 7 дней). Если пользователь \
сам называет длительность в днях — используй её, а не дни между датами.
- Год не указан — бери год из текущего плана (см. «Старт проекта» ниже).

Переспрашивай в двух случаях:
1. Действие деструктивно-неоднозначно: например, «удали задачу вёрстки» \
подходит под несколько задач и удаление нельзя отменить неявно — уточни, какую \
именно.
2. Запрос субъективный или не даёт критерия для конкретного изменения через \
инструменты («сделай план красивее», «сделай план лучше», «оптимизируй план» \
без деталей). У тебя нет инструмента «переименовать красиво» или «улучшить» — \
есть только конкретные мутации (сроки, исполнители, зависимости, задачи). Не \
изобретай никакую понравившуюся тебе мутацию (эмодзи в названиях, случайные \
переименования и т.п.) просто чтобы что-то сделать — вместо этого спроси, что \
именно пользователь имеет в виду (сроки? нагрузка? структура зависимостей?), \
и не вызывай ни одного инструмента, пока не поймёшь конкретное намерение.

Одного уточняющего вопроса достаточно. История диалога тебе доступна: если \
пользователь уже ответил на твой вопрос (в истории есть его ответ), НЕ \
переспрашивай снова — действуй по полученному ответу.

Каждое новое сообщение — самостоятельная просьба. История диалога нужна, чтобы
понимать ответы на твои уточняющие вопросы, но НЕ продолжай предыдущую задачу,
если новая просьба о другом («передвинь все задачи» после переназначения — это
сдвиг, а не продолжение переназначения).

Опечатки и разговорные формы интерпретируй по смыслу: «переднвинь» = «передвинь»,
«увилич» = «увеличь», «удоли» = «удали». Не переспрашивай из-за опечатки.

«Все задачи» = все задачи плана целиком: вызывай shift_tasks без assignee.

Если в одном сообщении несколько независимых просьб («добавь задачу для Марии \
и удали задачу у Олега») — выполни ВСЕ их за один ход, вызвав нужные инструменты \
подряд, а не по одной за раз.

Технические правила:
- Ты можешь изменять план ТОЛЬКО через доступные инструменты (tools). \
Никогда не выдумывай изменения плана в тексте ответа — только вызовом инструмента.
- Никогда не изобретай id задач. Используй только существующие id из плана.
- Если инструмент отклонил изменение (ошибка валидации, цикл зависимостей, \
несуществующая задача и т.п.) — объясни пользователю простыми словами, почему \
изменение не применено, и предложи, что можно сделать вместо этого.
- Если пользователь просит отменить, откатить последнее изменение («отмени», \
«отмени последнее изменение», «откати правку») — вызови инструмент \
undo_last_turn. Он откатывает план к состоянию до последней применённой мутации.
- Без эмодзи. Отвечай кратко и по-русски.
"""


class LLM(Protocol):
    def create(self, messages: list[dict], tools: list[dict]) -> dict: ...


def _history_messages(history: list[dict] | None) -> list[dict]:
    """Maps prior chat turns (role: "user"|"agent") onto OpenAI-shaped chat
    messages (user->user, agent->assistant), capped to the most recent
    HISTORY_CAP entries. Without this, each POST /api/chat only ever saw the
    latest message, so the model had no memory of its own prior questions and
    would re-ask things the user had already answered."""
    if not history:
        return []
    capped = history[-HISTORY_CAP:]
    mapped = []
    for turn in capped:
        role = turn.get("role")
        text = turn.get("text", "")
        if role == "user":
            mapped.append({"role": "user", "content": text})
        elif role == "agent":
            mapped.append({"role": "assistant", "content": text})
    return mapped


def run_agent_turn(
    message: str,
    plan: Plan,
    llm: "LLM",
    history: list[dict] | None = None,
    undo_callback: Callable[[], Plan] | None = None,
) -> Iterator[dict[str, Any]]:
    """Runs one agent turn: loops calling llm.create with tool schemas, dispatching
    any tool calls against a working copy of the plan, and streaming events.

    `history` is the prior chat turns in this conversation (list of
    {"role": "user"|"agent", "text": str}), folded into the LLM messages
    before the new `message` so the model has memory across turns - each
    /api/chat call is otherwise stateless. Capped to the last HISTORY_CAP
    entries.

    `undo_callback`, if given, is invoked instead of `dispatch()` whenever the
    model calls the `undo_last_turn` tool. Undo lives in the store's snapshot
    stack (see api/store.py), not in the plan value this function operates
    on, so it can't be expressed as a plain `api/tools.py` function - the
    caller (api/index.py's chat route) wires this to `store.undo()` followed
    by `store.get_plan()`, returning the restored Plan. Without a callback
    (e.g. no caller wired one up), the tool call yields an honest error
    instead of silently no-op'ing.

    Yields dicts of shape:
      {"type": "tool_call", "tool": name, "args": args}
      {"type": "patch", "plan_patch": PlanPatch.model_dump()}
      {"type": "message", "text": str}
      {"type": "error", "detail": str}
      {"type": "done"}
    """
    working_plan = plan
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        # The model gets the current plan (with real task ids) up front, so it
        # can resolve "после вёрстки" → the right id immediately instead of
        # looping on get_plan.
        {
            "role": "system",
            "content": "Текущий план (id · название · исполнитель · длительность · старт→конец · предшественники):\n"
            + compact_plan(working_plan),
        },
        *_history_messages(history),
        {"role": "user", "content": message},
    ]

    for _ in range(MAX_TURNS):
        result = llm.create(messages, TOOL_SCHEMAS)
        tool_calls = result.get("tool_calls")

        if tool_calls:
            # Echo the assistant turn (with its tool_calls) into the history —
            # required by the OpenAI/OpenRouter protocol: a `tool` result must
            # follow an assistant message that declared the matching call id.
            messages.append({
                "role": "assistant",
                "content": result.get("content") or None,
                "tool_calls": [
                    {
                        "id": call.get("id", f"call_{i}"),
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                    for i, call in enumerate(tool_calls)
                ],
            })
            for i, call in enumerate(tool_calls):
                name = call["name"]
                args = call.get("arguments", {})
                call_id = call.get("id", f"call_{i}")
                yield {"type": "tool_call", "tool": name, "args": args}
                if name == "undo_last_turn":
                    if undo_callback is None:
                        err = (
                            "Откат недоступен в этом режиме: нет доступа к истории снапшотов. "
                            "Используйте кнопку «Откатить» в интерфейсе."
                        )
                        yield {"type": "error", "detail": err}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": f"Ошибка: {err}",
                        })
                        continue
                    restored = undo_callback()
                    working_plan = restored
                    patch = PlanPatch(plan=restored, changed_ids=[])
                    yield {"type": "patch", "plan_patch": patch.model_dump()}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"OK, откат выполнен.\nПлан теперь:\n{compact_plan(working_plan)}",
                    })
                    continue
                try:
                    patch = dispatch(name, args, working_plan)
                except ToolError as e:
                    yield {"type": "error", "detail": str(e)}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"Ошибка: {e}",
                    })
                    continue
                working_plan = patch.plan
                yield {"type": "patch", "plan_patch": patch.model_dump()}
                # Feed the REAL result back to the model. For get_plan that's
                # the plan itself (otherwise the model asks again in a loop);
                # for mutations — a confirmation plus the updated plan snapshot
                # so follow-up calls use fresh ids/durations.
                if name == "get_plan":
                    tool_result = compact_plan(working_plan)
                else:
                    tool_result = (
                        f"OK, применено. Изменённые задачи: {patch.changed_ids or []}.\n"
                        f"План теперь:\n{compact_plan(working_plan)}"
                    )
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_result,
                })
            continue

        content = result.get("content", "")
        yield {"type": "message", "text": content}
        break

    yield {"type": "done"}


class MockLLM:
    """Deterministic LLM stub for tests and E2E: keyword-matches the latest user
    message to a scripted tool call, then returns a closing message on the next
    call so the agent loop terminates."""

    def __init__(self) -> None:
        self._done = False

    def create(self, messages: list[dict], tools: list[dict]) -> dict:
        if self._done:
            return {"content": "Готово."}

        self._done = True
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        text = user_text.lower()

        if "олег" in text and ("недел" in text or "перенес" in text or "перенеси" in text):
            return {"tool_calls": [{"id": "1", "name": "shift_tasks",
                    "arguments": {"assignee": "Олег", "days": 7}}]}
        if "мари" in text and "петр" in text:
            return {"tool_calls": [{"id": "1", "name": "reassign_tasks",
                    "arguments": {"from_assignee": "Мария", "to_assignee": "Пётр"}}]}
        if "добавь" in text and "аналитик" in text:
            # Predecessor is given by NAME on purpose — exercises the
            # name→id resolution in tool_registry the way a real LLM does.
            return {"tool_calls": [{"id": "1", "name": "add_task",
                    "arguments": {"name": "Настройка аналитики", "description": "",
                                  "assignee": "Иван", "duration_days": 3,
                                  "predecessors": ["Вёрстка и интеграция"]}}]}
        if "отмени" in text or "отменить" in text or "откати" in text or "откатить" in text:
            return {"tool_calls": [{"id": "1", "name": "undo_last_turn", "arguments": {}}]}

        self._done = False  # no tool call was made; next call should still terminate
        return {"content": "Готово."}


class OpenRouterLLM:
    """Wraps the OpenRouter-hosted chat completions API (OpenAI-compatible client),
    normalizing the response into the same shape MockLLM produces. Not covered by
    unit tests (requires network + API key).

    Resilience is a cascade over (key, model) pairs: primary model on the
    primary key, fallback model on the primary key, then the same two models
    on the fallback key (env `OPENROUTER_API_KEY_FALLBACK`, optional). So a
    key hitting its credit limit mid-demo degrades to the reserve key instead
    of an error in the chat."""

    PRIMARY_MODEL = "anthropic/claude-sonnet-4.5"
    FALLBACK_MODEL = "openai/gpt-4o"

    def __init__(self) -> None:
        import openai

        keys = [os.environ["OPENROUTER_API_KEY"]]
        fallback_key = os.getenv("OPENROUTER_API_KEY_FALLBACK")
        if fallback_key:
            keys.append(fallback_key)
        self._clients = [
            openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=k)
            for k in keys
        ]

    def _complete(self, client, model: str, messages: list[dict], tools: list[dict]):
        return client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
        )

    def create(self, messages: list[dict], tools: list[dict]) -> dict:
        response = None
        last_error: Exception | None = None
        for client in self._clients:
            for model in (self.PRIMARY_MODEL, self.FALLBACK_MODEL):
                try:
                    response = self._complete(client, model, messages, tools)
                    break
                except Exception as e:
                    last_error = e
            if response is not None:
                break
        if response is None:
            raise last_error if last_error else RuntimeError("no OpenRouter response")

        choice = response.choices[0].message
        raw_tool_calls = getattr(choice, "tool_calls", None)
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                import json as _json

                args = tc.function.arguments
                if isinstance(args, str):
                    args = _json.loads(args) if args else {}
                tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
            return {"tool_calls": tool_calls}

        return {"content": choice.content or ""}


def default_llm() -> "LLM":
    if os.getenv("MOCK_LLM") == "1" or os.getenv("ENV") == "test":
        return MockLLM()
    return OpenRouterLLM()
