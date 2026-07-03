from __future__ import annotations

import io

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from api.excel import ImportError_, export_plan, import_plan
from api.scheduler import compute_schedule
from api.store import get_store
from api.tools import ToolError

app = FastAPI(title="AI Gantt Planner")

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _plan_and_schedule() -> dict:
    store = get_store()
    plan = store.get_plan()
    schedule = compute_schedule(plan)
    return {
        "plan": plan.model_dump(),
        "schedule": [s.model_dump() for s in schedule],
    }


@app.get("/api/plan")
def get_plan() -> dict:
    return _plan_and_schedule()


@app.post("/api/reset")
def reset_plan() -> dict:
    store = get_store()
    store.reset_to_seed()
    return _plan_and_schedule()


@app.get("/api/plan/export")
def export_plan_route() -> StreamingResponse:
    store = get_store()
    plan = store.get_plan()
    data = export_plan(plan)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="plan.xlsx"'},
    )


@app.post("/api/plan/import")
async def import_plan_route(file: UploadFile) -> dict:
    store = get_store()
    data = await file.read()
    try:
        plan = import_plan(data)
    except (ImportError_, ToolError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    store.save_plan(plan)
    return _plan_and_schedule()
