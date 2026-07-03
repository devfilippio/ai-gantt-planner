from __future__ import annotations

import io
import json
import os

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import agent
from api.excel import ImportError_, export_plan, import_plan
from api.mcp_server import router as mcp_router
from api.scheduler import compute_schedule
from api.store import get_store
from api.tools import ToolError

app = FastAPI(title="AI Gantt Planner")
app.include_router(mcp_router)


class ChatRequest(BaseModel):
    message: str

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


@app.post("/api/chat")
def chat_route(body: ChatRequest) -> StreamingResponse:
    store = get_store()
    plan = store.get_plan()
    llm = agent.default_llm()

    def event_stream():
        snapshotted = False
        for event in agent.run_agent_turn(body.message, plan, llm=llm):
            if event["type"] == "patch":
                if not snapshotted:
                    store.snapshot()
                    snapshotted = True
                store.save_plan(agent_plan_from_patch(event))
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def agent_plan_from_patch(event: dict):
    from api.models import Plan

    return Plan.model_validate(event["plan_patch"]["plan"])


@app.post("/api/undo")
def undo_route() -> dict:
    store = get_store()
    store.undo()
    return _plan_and_schedule()


@app.post("/api/agent-test-mutation")
def agent_test_mutation_route() -> dict:
    """Test-only route: snapshots the current plan then deletes its first
    task, so tests can exercise /api/undo without going through the full
    agent/LLM stack. Guarded at request time so it is only active when
    ENV=test, regardless of module import order across the test suite."""
    if os.getenv("ENV") != "test":
        raise HTTPException(status_code=404, detail="Not Found")

    from api.tools import delete_task

    store = get_store()
    store.snapshot()
    plan = store.get_plan()
    first_id = plan.tasks[0].id
    patch = delete_task(plan, id=first_id)
    store.save_plan(patch.plan)
    return _plan_and_schedule()
