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


def test_chat_streams_sse(monkeypatch):
    from api import agent
    monkeypatch.setattr(agent, "default_llm", lambda: FakeLLM())
    client.post("/api/reset")
    with client.stream("POST", "/api/chat", json={"message": "переназначь Марию на Петра"}) as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert "event: patch" in body or '"type": "patch"' in body
    assert "done" in body
