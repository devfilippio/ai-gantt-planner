from api.agent import compact_plan, run_agent_turn
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


def test_agent_injects_history_into_llm_messages():
    """Regression for the no-memory bug: each POST /api/chat only sent the
    latest message, so the model re-asked clarifying questions it had already
    gotten answers to. run_agent_turn must fold prior turns (history) into the
    messages sent to the LLM, mapped user->user and agent->assistant, before
    the final new user message."""
    plan = seed_plan()
    llm = RecordingLLM()
    history = [
        {"role": "user", "text": "добавь задачу для Анны"},
        {"role": "agent", "text": "Уточните название и длительность"},
    ]
    list(run_agent_turn("называется Ретро, 2 дня", plan, llm=llm, history=history))

    # RecordingLLM's *first* call already gets the full messages list, but it
    # only records on the second call. Use a simpler recorder-first-call LLM
    # to check the first call's messages directly.
    class FirstCallRecorder:
        def __init__(self):
            self.first_call_messages = None

        def create(self, messages, tools):
            if self.first_call_messages is None:
                self.first_call_messages = [dict(m) for m in messages]
            return {"content": "Готово."}

    recorder = FirstCallRecorder()
    list(run_agent_turn("называется Ретро, 2 дня", plan, llm=recorder, history=history))

    msgs = recorder.first_call_messages
    assert msgs is not None
    # history user/agent turns must appear before the final user message,
    # mapped to user/assistant roles respectively.
    contents = [(m["role"], m.get("content")) for m in msgs]
    assert ("user", "добавь задачу для Анны") in contents
    assert ("assistant", "Уточните название и длительность") in contents
    assert contents[-1] == ("user", "называется Ретро, 2 дня")
    # history entry must come before the final message in the list.
    history_user_idx = next(i for i, c in enumerate(contents) if c == ("user", "добавь задачу для Анны"))
    final_idx = len(contents) - 1
    assert history_user_idx < final_idx


def test_agent_history_is_capped_at_last_20_entries():
    plan = seed_plan()

    class FirstCallRecorder:
        def __init__(self):
            self.first_call_messages = None

        def create(self, messages, tools):
            if self.first_call_messages is None:
                self.first_call_messages = [dict(m) for m in messages]
            return {"content": "Готово."}

    long_history = [{"role": "user", "text": f"сообщение {i}"} for i in range(30)]
    recorder = FirstCallRecorder()
    list(run_agent_turn("финальное сообщение", plan, llm=recorder, history=long_history))

    msgs = recorder.first_call_messages
    history_derived = [m for m in msgs if m["role"] in ("user", "assistant") and m["content"] != "финальное сообщение"]
    assert len(history_derived) == 20
    # Only the most recent 20 of the 30 should survive (messages 10..29).
    assert history_derived[0]["content"] == "сообщение 10"
    assert history_derived[-1]["content"] == "сообщение 29"


def test_compact_plan_includes_computed_dates_and_header():
    """compact_plan must surface computed start/end dates (via
    compute_schedule) so the model can reason about calendar dates when the
    user says things like 'с 11 по 18 мая' — not just duration in days."""
    plan = seed_plan()
    text = compact_plan(plan)
    assert f"Старт проекта: {plan.project_start}." in text
    assert "Сегодня:" in text
    # per-task lines should show a start->end date range, not just duration.
    assert "research" in text
    assert plan.project_start in text  # research starts at project_start


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


class UndoLLM:
    """Always calls undo_last_turn, then finishes."""

    def __init__(self) -> None:
        self.calls = 0

    def create(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"tool_calls": [{"id": "1", "name": "undo_last_turn", "arguments": {}}]}
        return {"content": "Откат выполнен."}


def test_agent_undo_last_turn_uses_callback():
    """undo_last_turn has no plan-level implementation (undo lives in the
    store's snapshot stack) - run_agent_turn must invoke the optional
    undo_callback instead of api.tool_registry.dispatch, and surface its
    result as a normal patch event."""
    plan = seed_plan()
    restored_plan = seed_plan()  # any distinguishable Plan value stands in for "the restored one"
    restored_plan.tasks[0].description = "restored-marker"

    calls = {"n": 0}

    def fake_undo_callback():
        calls["n"] += 1
        return restored_plan

    events = list(run_agent_turn(
        "отмени последнее изменение", plan, llm=UndoLLM(), undo_callback=fake_undo_callback,
    ))
    assert calls["n"] == 1
    types = [e["type"] for e in events]
    assert "patch" in types
    assert "error" not in types
    patch_event = [e for e in events if e["type"] == "patch"][-1]
    assert patch_event["plan_patch"]["plan"]["tasks"][0]["description"] == "restored-marker"


def test_agent_undo_last_turn_without_callback_is_honest_error():
    """Callers that don't wire an undo_callback (e.g. a bare script) must get
    a clear error event - never a silent no-op and never a crash."""
    plan = seed_plan()
    events = list(run_agent_turn("отмени последнее изменение", plan, llm=UndoLLM()))
    types = [e["type"] for e in events]
    assert "error" in types
    assert "patch" not in types
    error_event = [e for e in events if e["type"] == "error"][-1]
    assert "Откат" in error_event["detail"] or "откат" in error_event["detail"].lower()


def test_mock_llm_routes_undo_keywords_to_undo_last_turn():
    from api.agent import MockLLM

    plan = seed_plan()
    restored = seed_plan()

    events = list(run_agent_turn(
        "отмени последнее изменение", plan, llm=MockLLM(),
        undo_callback=lambda: restored,
    ))
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls and tool_calls[0]["tool"] == "undo_last_turn"
