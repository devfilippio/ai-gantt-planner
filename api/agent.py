from __future__ import annotations

import json
import os
from typing import Any, Iterator, Protocol

from api.models import Plan
from api.tool_registry import TOOL_SCHEMAS, dispatch
from api.tools import ToolError

MAX_TURNS = 8


def compact_plan(plan: Plan) -> str:
    """A small, LLM-friendly listing of the current plan so the model always
    knows the real task ids (and can resolve a user's "после вёрстки" to the
    right id) without having to loop on get_plan."""
    if not plan.tasks:
        return "(план пуст)"
    lines = []
    for t in plan.tasks:
        preds = ", ".join(t.predecessors) if t.predecessors else "—"
        lines.append(
            f"{t.id} · {t.name} · {t.assignee} · {t.duration_days}д · предшественники: {preds}"
        )
    return "\n".join(lines)

SYSTEM_PROMPT = """\
Ты — ассистент по управлению планом проекта (диаграмма Ганта).

Правила:
- Ты можешь изменять план ТОЛЬКО через доступные инструменты (tools). \
Никогда не выдумывай изменения плана в тексте ответа — только вызовом инструмента.
- Никогда не изобретай id задач. Используй только существующие id из плана. \
Если нужного id нет или запрос неоднозначен — спроси пользователя, не гадай.
- Если запрос двусмысленный (неясно, какую задачу/исполнителя имеют в виду), \
задай уточняющий вопрос вместо того, чтобы вызывать инструмент наугад.
- Если инструмент отклонил изменение (ошибка валидации, цикл зависимостей, \
несуществующая задача и т.п.) — объясни пользователю простыми словами, почему \
изменение не применено, и предложи, что можно сделать вместо этого.
- Отвечай кратко и по-русски.
"""


class LLM(Protocol):
    def create(self, messages: list[dict], tools: list[dict]) -> dict: ...


def run_agent_turn(message: str, plan: Plan, llm: "LLM") -> Iterator[dict[str, Any]]:
    """Runs one agent turn: loops calling llm.create with tool schemas, dispatching
    any tool calls against a working copy of the plan, and streaming events.

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
            "content": "Текущий план (id · название · исполнитель · длительность · предшественники):\n"
            + compact_plan(working_plan),
        },
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

        self._done = False  # no tool call was made; next call should still terminate
        return {"content": "Готово."}


class OpenRouterLLM:
    """Wraps the OpenRouter-hosted chat completions API (OpenAI-compatible client),
    normalizing the response into the same shape MockLLM produces. Not covered by
    unit tests (requires network + API key)."""

    PRIMARY_MODEL = "anthropic/claude-sonnet-4.5"
    FALLBACK_MODEL = "openai/gpt-4o"

    def __init__(self) -> None:
        import openai

        self._client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def _complete(self, model: str, messages: list[dict], tools: list[dict]):
        return self._client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
        )

    def create(self, messages: list[dict], tools: list[dict]) -> dict:
        try:
            response = self._complete(self.PRIMARY_MODEL, messages, tools)
        except Exception:
            response = self._complete(self.FALLBACK_MODEL, messages, tools)

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
