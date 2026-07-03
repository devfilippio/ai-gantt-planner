import os

os.environ["ENV"] = "test"

from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_undo_restores_previous_plan():
    client.post("/api/reset")
    before = len(client.get("/api/plan").json()["plan"]["tasks"])
    # simulate a mutation via import of a smaller plan is heavy; use delete endpoint proxy:
    client.post("/api/agent-test-mutation")  # test-only route that snapshots then deletes one task
    assert len(client.get("/api/plan").json()["plan"]["tasks"]) == before - 1
    client.post("/api/undo")
    assert len(client.get("/api/plan").json()["plan"]["tasks"]) == before
