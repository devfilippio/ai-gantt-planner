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
