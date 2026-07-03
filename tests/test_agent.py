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
