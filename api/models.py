from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class Task(BaseModel):
    id: str
    name: str
    description: str = ""
    assignee: str = ""
    duration_days: int = Field(gt=0)
    predecessors: list[str] = Field(default_factory=list)
    color_hint: str | None = None
    lead_days: int = Field(default=0, ge=0)
    """Extra calendar days to wait before the task can start, applied after the
    later of (predecessors' end, project start). Lets an independent task (no
    predecessors) start on a specific calendar date instead of always at
    project_start, and lets a dependent task start some days after its
    predecessors finish instead of immediately."""

    @field_validator("predecessors")
    @classmethod
    def no_self_reference(cls, v: list[str], info) -> list[str]:
        tid = info.data.get("id")
        if tid is not None and tid in v:
            raise ValueError(f"Task '{tid}' cannot list itself as a predecessor")
        return v


class Scheduled(BaseModel):
    id: str
    start: str  # ISO date
    end: str    # ISO date (exclusive end = start + duration)
    is_critical: bool = False


def _today_iso() -> str:
    return date.today().isoformat()


class Plan(BaseModel):
    tasks: list[Task] = Field(default_factory=list)
    project_start: str = Field(default_factory=_today_iso)


class PlanPatch(BaseModel):
    """Full plan after a mutation, plus which task ids changed (for UI highlight).

    `schedule` is left unset by the tool layer (tools.py never computes it —
    scheduling is the caller's concern) and is filled in by the SSE
    formatting layer in api/index.py before the patch event reaches the
    frontend, since the Gantt chart needs computed start/end dates to
    reposition bars after an agent edit."""
    plan: Plan
    changed_ids: list[str] = Field(default_factory=list)
    schedule: list[Scheduled] | None = None
