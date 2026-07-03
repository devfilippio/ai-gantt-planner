from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Task(BaseModel):
    id: str
    name: str
    description: str = ""
    assignee: str = ""
    duration_days: int = Field(gt=0)
    predecessors: list[str] = Field(default_factory=list)
    color_hint: str | None = None

    @field_validator("predecessors")
    @classmethod
    def no_self_reference(cls, v: list[str], info) -> list[str]:
        return v


class Scheduled(BaseModel):
    id: str
    start: str  # ISO date
    end: str    # ISO date (exclusive end = start + duration)
    is_critical: bool = False


class Plan(BaseModel):
    tasks: list[Task] = Field(default_factory=list)
    project_start: str = "2026-05-05"


class PlanPatch(BaseModel):
    """Full plan after a mutation, plus which task ids changed (for UI highlight)."""
    plan: Plan
    changed_ids: list[str] = Field(default_factory=list)
