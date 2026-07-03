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
