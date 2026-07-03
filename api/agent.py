from __future__ import annotations

import os
from typing import Any, Iterator, Protocol

from api.models import Plan
from api.tool_registry import TOOL_SCHEMAS, dispatch
from api.tools import ToolError

MAX_TURNS = 6

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
        {"role": "user", "content": message},
    ]

    for _ in range(MAX_TURNS):
        result = llm.create(messages, TOOL_SCHEMAS)
        tool_calls = result.get("tool_calls")

        if tool_calls:
            for call in tool_calls:
                name = call["name"]
                args = call.get("arguments", {})
                yield {"type": "tool_call", "tool": name, "args": args}
                try:
                    patch = dispatch(name, args, working_plan)
                except ToolError as e:
                    yield {"type": "error", "detail": str(e)}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": f"error: {e}",
                    })
                    continue
                working_plan = patch.plan
                yield {"type": "patch", "plan_patch": patch.model_dump()}
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": "ok",
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
