import json

from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


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


def _parse_sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload:
            events.append(json.loads(payload))
    return events


def test_chat_streams_sse(monkeypatch):
    from api import agent
    monkeypatch.setattr(agent, "default_llm", lambda: FakeLLM())
    client.post("/api/reset")
    with client.stream("POST", "/api/chat", json={"message": "переназначь Марию на Петра"}) as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert "event: patch" in body or '"type": "patch"' in body
    assert "done" in body


def test_chat_accepts_history_array(monkeypatch):
    """POST /api/chat must accept an optional `history` array of prior turns
    (role: user/agent) without erroring, and actually thread it through to
    the agent so a real LLM can use it for follow-up context."""
    from api import agent

    captured = {}

    class RecordingLLM:
        def create(self, messages, tools):
            captured["messages"] = messages
            return {"content": "Готово."}

    monkeypatch.setattr(agent, "default_llm", lambda: RecordingLLM())
    client.post("/api/reset")

    body = {
        "message": "называется Ретро, 2 дня",
        "history": [
            {"role": "user", "text": "добавь задачу для Анны"},
            {"role": "agent", "text": "Уточните название и длительность"},
        ],
    }
    with client.stream("POST", "/api/chat", json=body) as r:
        assert r.status_code == 200
        body_text = "".join(chunk for chunk in r.iter_text())

    assert "done" in body_text
    msgs = captured["messages"]
    contents = [(m["role"], m.get("content")) for m in msgs]
    assert ("user", "добавь задачу для Анны") in contents
    assert ("assistant", "Уточните название и длительность") in contents
    assert contents[-1] == ("user", "называется Ретро, 2 дня")


def test_chat_patch_event_includes_recomputed_schedule(monkeypatch):
    """The `patch` event must carry a `schedule` alongside plan/changed_ids —
    without it the frontend has no start/end dates to reposition Gantt bars
    against after an agent edit (see api/index.py chat_route)."""
    from api import agent
    monkeypatch.setattr(agent, "default_llm", lambda: FakeLLM())
    reset_resp = client.post("/api/reset")
    plan = reset_resp.json()["plan"]

    with client.stream("POST", "/api/chat", json={"message": "переназначь Марию на Петра"}) as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())

    events = _parse_sse_events(body)
    patch_events = [e for e in events if e.get("type") == "patch"]
    assert patch_events, "expected at least one patch event"

    for patch_event in patch_events:
        plan_patch = patch_event["plan_patch"]
        assert "schedule" in plan_patch
        schedule = plan_patch["schedule"]
        assert schedule is not None
        assert len(schedule) == len(plan["tasks"])


class UndoOnlyLLM:
    """Always calls undo_last_turn, then finishes - drives /api/chat's real
    undo_callback wiring (store.undo + store.get_plan) end to end."""

    def __init__(self):
        self.calls = 0

    def create(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"tool_calls": [{"id": "1", "name": "undo_last_turn", "arguments": {}}]}
        return {"content": "Откат выполнен."}


def test_chat_undo_last_turn_restores_plan_via_store(monkeypatch):
    """'отмени последнее изменение' in chat must actually restore the plan
    that was there before the previous agent mutation, using the real store's
    snapshot stack - not just claim it did."""
    from api import agent

    client.post("/api/reset")
    before_count = len(client.get("/api/plan").json()["plan"]["tasks"])

    monkeypatch.setattr(agent, "default_llm", lambda: FakeLLM())
    with client.stream("POST", "/api/chat", json={"message": "переназначь Марию на Петра"}) as r:
        "".join(chunk for chunk in r.iter_text())
    mutated = client.get("/api/plan").json()["plan"]
    assert any(t["assignee"] == "Пётр" for t in mutated["tasks"])

    monkeypatch.setattr(agent, "default_llm", lambda: UndoOnlyLLM())
    with client.stream("POST", "/api/chat", json={"message": "отмени последнее изменение"}) as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())

    events = _parse_sse_events(body)
    assert any(e.get("type") == "patch" for e in events)
    assert not any(e.get("type") == "error" for e in events)

    restored = client.get("/api/plan").json()["plan"]
    assert len(restored["tasks"]) == before_count
    assert not any(t["assignee"] == "Пётр" for t in restored["tasks"])


def test_chat_undo_last_turn_does_not_pollute_snapshot_stack(monkeypatch):
    """Regression: the chat route's generic patch handler used to call
    store.snapshot() unconditionally on the first patch event of a turn -
    including the patch produced by undo_last_turn itself. That pushed the
    just-restored plan back onto the snapshot stack, so a subsequent
    /api/undo would be a no-op instead of going one step further back."""
    from api import agent

    client.post("/api/reset")
    original = client.get("/api/plan").json()["plan"]

    # Two real mutations, so there are two distinct prior states to undo to.
    monkeypatch.setattr(agent, "default_llm", lambda: FakeLLM())
    with client.stream("POST", "/api/chat", json={"message": "переназначь Марию на Петра"}) as r:
        "".join(chunk for chunk in r.iter_text())
    after_first_mutation = client.get("/api/plan").json()["plan"]

    client.post("/api/agent-test-mutation")  # snapshots then deletes task[0] - a second distinct state
    after_second_mutation = client.get("/api/plan").json()["plan"]
    assert after_second_mutation != after_first_mutation

    # Undo via chat should pop back to `after_first_mutation`.
    monkeypatch.setattr(agent, "default_llm", lambda: UndoOnlyLLM())
    with client.stream("POST", "/api/chat", json={"message": "отмени последнее изменение"}) as r:
        "".join(chunk for chunk in r.iter_text())
    after_chat_undo = client.get("/api/plan").json()["plan"]
    assert after_chat_undo == after_first_mutation

    # A second, independent undo (via the plain REST route) must go one step
    # further back to the original seed - not repeat the same restore because
    # the chat undo polluted the stack with a duplicate entry.
    client.post("/api/undo")
    after_second_undo = client.get("/api/plan").json()["plan"]
    assert after_second_undo == original
