from __future__ import annotations

import io
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import agent
from api.excel import ImportError_, export_plan, import_plan
from api.mcp_server import mcp, mcp_app
from api.scheduler import compute_schedule
from api.store import get_store
from api.tools import ToolError, update_task


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FastMCP's streamable-HTTP ASGI app relies on its session manager's
    # task group being active for the lifetime of the app. Since we mount
    # that sub-app inside this FastAPI app rather than running it
    # standalone, its own lifespan never fires unless we drive it from
    # here. Running it as the outer app's lifespan ensures the session
    # manager (stateless mode - no server-side session state) is started
    # before any request (including to unrelated routes like /api/health)
    # and cleaned up on shutdown.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AI Gantt Planner", lifespan=lifespan)
app.mount("/api/mcp", mcp_app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatHistoryTurn(BaseModel):
    """One prior turn of the conversation, as kept by the frontend's chat log.
    `role` is "user" for the human's messages and "agent" for the assistant's
    final text replies (tool-call chips and errors are not part of history —
    only the conversational back-and-forth the model needs to resolve
    follow-ups like "называется Ретро, 2 дня" after it asked a clarifying
    question)."""

    role: str
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatHistoryTurn] = []


class TaskUpdateRequest(BaseModel):
    """Partial update for a single task, used by the Gantt chart's manual
    drag/resize interaction. All fields optional — only provided fields are
    applied (mirrors `update_task`'s **fields semantics)."""

    duration_days: int | None = None
    start: str | None = None
    predecessors: list[str] | None = None
    assignee: str | None = None


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


MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB — an .xlsx task list is a few KB


@app.post("/api/plan/import")
async def import_plan_route(file: UploadFile) -> dict:
    store = get_store()
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл слишком большой (максимум 5 МБ)")
    if data[:2] != b"PK":  # every .xlsx is a zip archive
        raise HTTPException(status_code=400, detail="Ожидается файл .xlsx")
    try:
        plan = import_plan(data)
    except (ImportError_, ToolError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        # A malformed workbook must degrade to a clean 400, never a 500 —
        # and never reach store.save_plan with a half-parsed plan.
        raise HTTPException(status_code=400, detail="Не удалось разобрать файл — проверьте формат")
    store.save_plan(plan)
    return _plan_and_schedule()


@app.post("/api/chat")
def chat_route(body: ChatRequest) -> StreamingResponse:
    store = get_store()
    plan = store.get_plan()

    def event_stream():
        try:
            llm = agent.default_llm()
        except KeyError:
            # OPENROUTER_API_KEY not configured on the server. Surface a clean
            # chat error instead of a 500 so the deployed app degrades
            # gracefully (the Gantt, import/export and manual edits still work).
            yield f'data: {json.dumps({"type": "error", "detail": "LLM не настроен: задайте OPENROUTER_API_KEY на сервере."}, ensure_ascii=False)}\n\n'
            yield f'data: {json.dumps({"type": "done"}, ensure_ascii=False)}\n\n'
            return

        snapshotted = False
        history = [{"role": turn.role, "text": turn.text} for turn in body.history]
        for event in agent.run_agent_turn(body.message, plan, llm=llm, history=history):
            if event["type"] == "patch":
                if not snapshotted:
                    store.snapshot()
                    snapshotted = True
                patched_plan = agent_plan_from_patch(event)
                store.save_plan(patched_plan)
                # The Gantt chart never stores dates on tasks — they're always
                # computed by the scheduler. Without a recomputed schedule
                # here, the frontend has plan+changed_ids but no start/end
                # dates to reposition bars against, so the chart would sit
                # frozen after an agent edit. Enrich the patch event with the
                # freshly computed schedule so the store can reposition bars
                # live, in the same event the chip/highlight reacts to.
                schedule = compute_schedule(patched_plan)
                event["plan_patch"]["schedule"] = [s.model_dump() for s in schedule]
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


@app.post("/api/plan/task/{task_id}")
def update_task_route(task_id: str, body: TaskUpdateRequest) -> dict:
    """Lightweight single-task update used by the Gantt chart's manual
    drag/resize (Task 7.3). There is no persisted `start` on a Task — dates
    are always computed by the scheduler from duration + predecessors — so
    `start` is accepted for API forward-compatibility but has no effect;
    resizing a bar's duration is what actually moves dates.
    """
    store = get_store()
    plan = store.get_plan()
    try:
        patch = update_task(
            plan,
            id=task_id,
            duration_days=body.duration_days,
            predecessors=body.predecessors,
            assignee=body.assignee,
        )
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store.save_plan(patch.plan)
    result = _plan_and_schedule()
    result["changed_ids"] = patch.changed_ids
    return result


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
