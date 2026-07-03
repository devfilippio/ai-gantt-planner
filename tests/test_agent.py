from api.agent import run_agent_turn
from api.seed import seed_plan


class FakeLLM:
    """Yields one tool call then a final message."""
    def __init__(self):
        self.calls = 0

    def create(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"tool_calls": [{"id": "1", "name": "reassign_tasks",
                    "arguments": {"from_assignee": "Мария", "to_assignee": "Пётр"}}]}
        return {"content": "Готово, переназначил задачи Марии на Петра."}


def test_agent_applies_tool_and_streams_events():
    plan = seed_plan()
    events = list(run_agent_turn("переназначь Марию на Петра", plan, llm=FakeLLM()))
    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "patch" in types
    assert types[-1] == "done"
    final_patch = [e for e in events if e["type"] == "patch"][-1]
    assert any(t["assignee"] == "Пётр" for t in final_patch["plan_patch"]["plan"]["tasks"])


class RecordingLLM:
    """First call: asks for get_plan. Second call: records the messages it was
    given (to assert the loop feeds real tool results back) and finishes."""

    def __init__(self):
        self.calls = 0
        self.second_call_messages = None

    def create(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"tool_calls": [{"id": "t1", "name": "get_plan", "arguments": {}}]}
        self.second_call_messages = [dict(m) for m in messages]
        return {"content": "Готово."}


def test_agent_feeds_real_tool_results_back_to_model():
    """Regression for the get_plan loop bug: the model must receive (a) its own
    assistant message with the tool_calls it made, and (b) a tool result that
    contains the actual plan (task ids), not a bare 'ok' — otherwise a real
    LLM keeps calling get_plan until the turn limit and never mutates."""
    plan = seed_plan()
    llm = RecordingLLM()
    list(run_agent_turn("добавь задачу", plan, llm=llm))

    msgs = llm.second_call_messages
    assert msgs is not None
    roles = [m["role"] for m in msgs]
    assert "assistant" in roles, "assistant message with tool_calls must be echoed into history"
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert tool_msgs, "tool result message missing"
    # The get_plan result must contain real task ids, not 'ok'.
    assert "research" in tool_msgs[-1]["content"]
    assert tool_msgs[-1]["content"] != "ok"
    # The model also gets the plan up front (system context), so it can act
    # without calling get_plan at all.
    system_texts = " ".join(m["content"] or "" for m in msgs if m["role"] == "system")
    assert "research" in system_texts


def test_agent_mock_add_task_creates_task_with_resolved_predecessor():
    from api.agent import MockLLM

    plan = seed_plan()
    events = list(run_agent_turn(
        "Добавь задачу настройка аналитики, исполнитель Иван, 3 дня, после вёрстки",
        plan, llm=MockLLM(),
    ))
    patches = [e for e in events if e["type"] == "patch"]
    assert patches, "add_task must produce a patch"
    tasks = patches[-1]["plan_patch"]["plan"]["tasks"]
    assert len(tasks) == 8
    new = next(t for t in tasks if t["name"] == "Настройка аналитики")
    # Predecessor was given by NAME ("Вёрстка и интеграция") and must resolve
    # to the real task id.
    assert new["predecessors"] == ["frontend"]
