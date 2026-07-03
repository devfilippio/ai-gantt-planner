from fastapi.testclient import TestClient
from api.index import app

client = TestClient(app)


def test_get_plan_returns_seed():
    r = client.post("/api/reset")
    assert r.status_code == 200
    r = client.get("/api/plan")
    body = r.json()
    assert len(body["plan"]["tasks"]) >= 20
    assert len(body["schedule"]) == len(body["plan"]["tasks"])


def test_export_then_import_roundtrip():
    client.post("/api/reset")
    export = client.get("/api/plan/export")
    assert export.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    files = {"file": ("plan.xlsx", export.content,
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = client.post("/api/plan/import", files=files)
    assert r.status_code == 200
    assert len(r.json()["plan"]["tasks"]) >= 20


def test_update_task_duration_persists_and_reschedules():
    client.post("/api/reset")
    before = client.get("/api/plan").json()
    task_id = before["plan"]["tasks"][0]["id"]
    old_duration = before["plan"]["tasks"][0]["duration_days"]

    r = client.post(f"/api/plan/task/{task_id}", json={"duration_days": old_duration + 5})
    assert r.status_code == 200
    body = r.json()
    updated = next(t for t in body["plan"]["tasks"] if t["id"] == task_id)
    assert updated["duration_days"] == old_duration + 5
    assert body["changed_ids"] == [task_id]

    after = client.get("/api/plan").json()
    assert next(t for t in after["plan"]["tasks"] if t["id"] == task_id)["duration_days"] == old_duration + 5


def test_update_task_unknown_id_returns_400():
    client.post("/api/reset")
    r = client.post("/api/plan/task/does-not-exist", json={"duration_days": 3})
    assert r.status_code == 400
