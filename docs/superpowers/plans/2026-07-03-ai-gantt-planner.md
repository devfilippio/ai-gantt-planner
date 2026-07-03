# AI Gantt Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an AI-native web app where a user sees a seeded interactive Gantt chart, edits the plan in bulk via a natural-language chat agent (changes stream live onto the chart), imports/exports Excel, and the same tool layer is exposed over MCP — deployed on Vercel.

**Architecture:** Monorepo, single Vercel project. React (Vite) SPA under `frontend/`, FastAPI Python serverless functions under `api/`. A single `tools.py` module holds all plan-mutation logic and is consumed by both the internal LLM agent (OpenRouter, streamed over SSE) and an MCP streamable-HTTP server. Task dates are never stored — they are computed from durations + predecessors by a pure scheduler. State persists in Neon Postgres.

**Tech Stack:** Vite + React 19 + TypeScript + Zustand; Python 3.13 + FastAPI + Pydantic + openpyxl + official `mcp` SDK + OpenRouter (openai client); Neon Postgres (`psycopg`); Vercel.

**Reference docs to read before starting:**
- Spec: `docs/superpowers/specs/2026-07-03-ai-gantt-planner-design.md`
- Design system: `D:\AI\misite\filipp.io\CLAUDE.md`
- Approved mockup: widget in the 2026-07-03 session

**Conventions:**
- Code, comments, commits, README: English. Chat/docs with owner: Russian.
- Secrets only in env; `.env` already gitignored.
- Windows/PowerShell host — when running Python that prints Cyrillic, set `PYTHONIOENCODING=utf-8`.
- Commit after every green test. Use `git -c user.name="flowz" -c user.email="pushkina.dt@gmail.com"` if identity is unset.

---

## Phase 0: Project scaffolding

### Task 0.1: Repo structure and Python deps

**Files:**
- Create: `requirements.txt`, `api/__init__.py`, `api/index.py`, `tests/__init__.py`, `pytest.ini`, `.python-version`

- [ ] **Step 1: Create `requirements.txt`**

```text
fastapi==0.115.6
pydantic==2.10.4
openpyxl==3.1.5
openai==1.59.6
mcp==1.2.0
psycopg[binary]==3.2.3
python-multipart==0.0.20
```

- [ ] **Step 2: Create `.python-version`**

```text
3.13
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 4: Create `api/__init__.py` and `tests/__init__.py`** (empty files)

- [ ] **Step 5: Create minimal `api/index.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="AI Gantt Planner")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Set up venv and install**

Run: `python -m venv .venv && .venv/Scripts/pip install -r requirements.txt && .venv/Scripts/pip install pytest httpx`
Expected: installs succeed.

- [ ] **Step 7: Smoke-test the app imports**

Run: `.venv/Scripts/python -c "from api.index import app; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .python-version pytest.ini api/ tests/
git commit -m "chore: scaffold FastAPI backend"
```

### Task 0.2: vercel.json routing

**Files:**
- Create: `vercel.json`

- [ ] **Step 1: Create `vercel.json`**

```json
{
  "buildCommand": "cd frontend && npm install && npm run build",
  "outputDirectory": "frontend/dist",
  "functions": {
    "api/index.py": { "maxDuration": 60 }
  },
  "rewrites": [
    { "source": "/api/(.*)", "destination": "/api/index" },
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

Note: all backend routes are served by the single `api/index.py` ASGI app (it internally routes `/api/chat`, `/api/mcp`, etc.). The SPA fallback rewrite is last so API wins.

- [ ] **Step 2: Commit**

```bash
git add vercel.json
git commit -m "chore: add vercel routing config"
```

---

## Phase 1: Backend core — models & scheduler

### Task 1.1: Pydantic models

**Files:**
- Create: `api/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
from api.models import Task, Plan


def test_task_requires_positive_duration():
    import pytest
    with pytest.raises(ValueError):
        Task(id="a", name="A", description="", assignee="X", duration_days=0, predecessors=[])


def test_plan_roundtrips_tasks():
    t = Task(id="a", name="A", description="d", assignee="X", duration_days=3, predecessors=[])
    plan = Plan(tasks=[t], project_start="2026-05-05")
    assert plan.tasks[0].duration_days == 3
    assert plan.project_start == "2026-05-05"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: api.models`.

- [ ] **Step 3: Implement `api/models.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add api/models.py tests/test_models.py
git commit -m "feat: add plan/task pydantic models"
```

### Task 1.2: Scheduler — date computation

**Files:**
- Create: `api/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
from api.models import Task, Plan
from api.scheduler import compute_schedule


def _plan(*tasks):
    return Plan(tasks=list(tasks), project_start="2026-05-05")


def test_single_task_starts_at_project_start():
    plan = _plan(Task(id="a", name="A", duration_days=3, predecessors=[]))
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["a"].start == "2026-05-05"
    assert sched["a"].end == "2026-05-08"  # 3 calendar days


def test_successor_starts_after_predecessor_end():
    plan = _plan(
        Task(id="a", name="A", duration_days=3, predecessors=[]),
        Task(id="b", name="B", duration_days=2, predecessors=["a"]),
    )
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["b"].start == "2026-05-08"
    assert sched["b"].end == "2026-05-10"


def test_task_with_two_predecessors_starts_after_latest():
    plan = _plan(
        Task(id="a", name="A", duration_days=3, predecessors=[]),
        Task(id="b", name="B", duration_days=7, predecessors=[]),
        Task(id="c", name="C", duration_days=1, predecessors=["a", "b"]),
    )
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["c"].start == "2026-05-12"  # after B (longer)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: api.scheduler`.

- [ ] **Step 3: Implement `compute_schedule` and topological order in `api/scheduler.py`**

```python
from __future__ import annotations

from datetime import date, timedelta

from api.models import Plan, Scheduled


class CycleError(ValueError):
    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__("Dependency cycle: " + " -> ".join(cycle))


def _topo_order(plan: Plan) -> list[str]:
    ids = {t.id for t in plan.tasks}
    preds = {t.id: [p for p in t.predecessors if p in ids] for t in plan.tasks}
    indeg = {i: 0 for i in ids}
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for tid, ps in preds.items():
        for p in ps:
            adj[p].append(tid)
            indeg[tid] += 1
    queue = [i for i in ids if indeg[i] == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if len(order) != len(ids):
        stuck = [i for i in ids if indeg[i] > 0]
        raise CycleError(stuck)
    return order


def compute_schedule(plan: Plan) -> list[Scheduled]:
    by_id = {t.id: t for t in plan.tasks}
    order = _topo_order(plan)
    start_d = date.fromisoformat(plan.project_start)
    starts: dict[str, date] = {}
    ends: dict[str, date] = {}
    for tid in order:
        t = by_id[tid]
        valid_preds = [p for p in t.predecessors if p in ends]
        s = max((ends[p] for p in valid_preds), default=start_d)
        e = s + timedelta(days=t.duration_days)
        starts[tid], ends[tid] = s, e
    result = [
        Scheduled(id=tid, start=starts[tid].isoformat(), end=ends[tid].isoformat())
        for tid in by_id
    ]
    _mark_critical(plan, starts, ends, result)
    return result


def _mark_critical(plan, starts, ends, result):
    if not ends:
        return
    project_end = max(ends.values())
    by_id = {t.id: t for t in plan.tasks}
    scheduled = {s.id: s for s in result}

    def on_critical(tid: str) -> bool:
        return ends[tid] == project_end or any(
            on_critical(succ.id)
            for succ in plan.tasks
            if tid in succ.predecessors and starts[succ.id] == ends[tid]
        )

    for tid in by_id:
        scheduled[tid].is_critical = on_critical(tid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_scheduler.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add api/scheduler.py tests/test_scheduler.py
git commit -m "feat: scheduler computes dates from durations and predecessors"
```

### Task 1.3: Scheduler — cycle detection & critical path

**Files:**
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Add failing tests**

```python
import pytest
from api.scheduler import CycleError


def test_cycle_raises_with_offending_ids():
    plan = _plan(
        Task(id="a", name="A", duration_days=1, predecessors=["b"]),
        Task(id="b", name="B", duration_days=1, predecessors=["a"]),
    )
    with pytest.raises(CycleError) as exc:
        compute_schedule(plan)
    assert set(exc.value.cycle) == {"a", "b"}


def test_critical_path_flag():
    plan = _plan(
        Task(id="a", name="A", duration_days=3, predecessors=[]),
        Task(id="b", name="B", duration_days=7, predecessors=[]),
        Task(id="c", name="C", duration_days=1, predecessors=["a", "b"]),
    )
    sched = {s.id: s for s in compute_schedule(plan)}
    assert sched["c"].is_critical is True
    assert sched["b"].is_critical is True   # longer branch feeds c
    assert sched["a"].is_critical is False  # slack
```

- [ ] **Step 2: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_scheduler.py -v`
Expected: PASS (5 tests total). If `test_critical_path_flag` fails, the recursion in `_mark_critical` needs the `starts[succ] == ends[tid]` chaining — already implemented; verify.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scheduler.py
git commit -m "test: cover cycle detection and critical path"
```

---

## Phase 2: Excel import/export

### Task 2.1: Excel export

**Files:**
- Create: `api/excel.py`
- Test: `tests/test_excel.py`

- [ ] **Step 1: Write the failing test**

```python
import io
from api.models import Task, Plan
from api.excel import export_plan, import_plan


def _plan():
    return Plan(tasks=[
        Task(id="a", name="Design", description="mockups", assignee="Maria", duration_days=3, predecessors=[]),
        Task(id="b", name="API", description="auth", assignee="Ivan", duration_days=5, predecessors=["a"]),
    ], project_start="2026-05-05")


def test_export_produces_readable_workbook():
    from openpyxl import load_workbook
    data = export_plan(_plan())
    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert headers == ["задача", "описание", "исполнитель", "длительность", "предшественники"]
    assert ws[2][0].value == "Design"
    assert ws[3][4].value == "Design"  # predecessor referenced by NAME
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_excel.py -v`
Expected: FAIL — `ModuleNotFoundError: api.excel`.

- [ ] **Step 3: Implement export in `api/excel.py`**

```python
from __future__ import annotations

import io

from openpyxl import Workbook, load_workbook

from api.models import Plan, Task

HEADERS = ["задача", "описание", "исполнитель", "длительность", "предшественники"]


def export_plan(plan: Plan) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "План"
    ws.append(HEADERS)
    name_by_id = {t.id: t.name for t in plan.tasks}
    for t in plan.tasks:
        preds = ", ".join(name_by_id.get(p, p) for p in t.predecessors)
        ws.append([t.name, t.description, t.assignee, t.duration_days, preds])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_excel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/excel.py tests/test_excel.py
git commit -m "feat: export plan to xlsx"
```

### Task 2.2: Excel import + round-trip + row-level errors

**Files:**
- Modify: `api/excel.py`, `tests/test_excel.py`

- [ ] **Step 1: Add failing tests**

```python
import pytest
from api.excel import ImportError_ as ExcelImportError


def test_import_roundtrips_export():
    original = _plan()
    data = export_plan(original)
    imported = import_plan(data)
    assert [t.name for t in imported.tasks] == ["Design", "API"]
    # predecessor name resolved back to an id
    api_task = next(t for t in imported.tasks if t.name == "API")
    design_task = next(t for t in imported.tasks if t.name == "Design")
    assert api_task.predecessors == [design_task.id]


def test_import_unknown_predecessor_reports_row():
    from openpyxl import Workbook
    import io
    wb = Workbook(); ws = wb.active
    ws.append(HEADERS_FOR_TEST := ["задача", "описание", "исполнитель", "длительность", "предшественники"])
    ws.append(["A", "", "X", 2, ""])
    ws.append(["B", "", "Y", 3, "Ghost"])
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(ExcelImportError) as exc:
        import_plan(buf.getvalue())
    assert "3" in str(exc.value)  # row number
    assert "Ghost" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_excel.py -v`
Expected: FAIL — `import_plan` / `ImportError_` undefined.

- [ ] **Step 3: Add import to `api/excel.py`**

```python
import re


class ImportError_(ValueError):
    pass


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "task"
    slug, i = base, 1
    while slug in taken:
        i += 1
        slug = f"{base}-{i}"
    taken.add(slug)
    return slug


def import_plan(data: bytes) -> Plan:
    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ImportError_("Пустой файл")
    taken: set[str] = set()
    raw = []
    name_to_id: dict[str, str] = {}
    for idx, row in enumerate(rows[1:], start=2):
        name = (row[0] or "").strip() if row[0] else ""
        if not name:
            continue
        try:
            duration = int(row[3])
        except (TypeError, ValueError):
            raise ImportError_(f"строка {idx}: некорректная длительность '{row[3]}'")
        if duration <= 0:
            raise ImportError_(f"строка {idx}: длительность должна быть > 0")
        tid = _slug(name, taken)
        name_to_id[name] = tid
        raw.append((idx, tid, name, row))
    tasks = []
    for idx, tid, name, row in raw:
        pred_names = [p.strip() for p in str(row[4] or "").replace(";", ",").split(",") if p.strip()]
        preds = []
        for pn in pred_names:
            if pn not in name_to_id:
                raise ImportError_(f"строка {idx}: предшественник '{pn}' не найден")
            preds.append(name_to_id[pn])
        tasks.append(Task(
            id=tid, name=name, description=str(row[1] or ""),
            assignee=str(row[2] or ""), duration_days=int(row[3]), predecessors=preds,
        ))
    return Plan(tasks=tasks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_excel.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add api/excel.py tests/test_excel.py
git commit -m "feat: import xlsx with row-level validation and round-trip"
```

---

## Phase 3: Tool layer (shared by agent + MCP)

### Task 3.1: Seed data

**Files:**
- Create: `api/seed.py`
- Test: `tests/test_seed.py`

- [ ] **Step 1: Write the failing test**

```python
from api.seed import seed_plan
from api.scheduler import compute_schedule


def test_seed_is_valid_and_schedules():
    plan = seed_plan()
    assert len(plan.tasks) >= 20
    assignees = {t.assignee for t in plan.tasks}
    assert len(assignees) >= 5
    sched = compute_schedule(plan)  # must not raise (no cycles)
    assert len(sched) == len(plan.tasks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: api.seed`.

- [ ] **Step 3: Implement `api/seed.py`** — a "Запуск мобильного приложения" plan with ≥20 tasks, 5 assignees (Мария, Иван, Олег, Анна, Дмитрий), branching predecessors. Build `Task` objects with stable slug ids. Return `Plan(tasks=..., project_start="2026-05-05")`. (Engineer fills realistic task names: research, design concept, UI kit, API auth, API payments, onboarding screen, payment integration, push notifications, QA regression, store publication, etc.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/seed.py tests/test_seed.py
git commit -m "feat: seed plan for mobile app launch"
```

### Task 3.2: Tool functions (pure, plan-in → PlanPatch-out)

**Files:**
- Create: `api/tools.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from api.models import Task, Plan
from api.tools import (
    add_task, update_task, delete_task, set_dependencies,
    reassign_tasks, shift_tasks, ToolError,
)


def _plan():
    return Plan(tasks=[
        Task(id="a", name="A", assignee="Ivan", duration_days=3, predecessors=[]),
        Task(id="b", name="B", assignee="Ivan", duration_days=2, predecessors=["a"]),
        Task(id="c", name="C", assignee="Oleg", duration_days=4, predecessors=["a"]),
    ], project_start="2026-05-05")


def test_add_task_appends_and_reports_change():
    patch = add_task(_plan(), name="D", description="", assignee="Anna", duration_days=2, predecessors=["b"])
    ids = {t.id for t in patch.plan.tasks}
    assert len(ids) == 4
    new_id = next(t.id for t in patch.plan.tasks if t.name == "D")
    assert patch.changed_ids == [new_id]


def test_update_task_changes_field():
    patch = update_task(_plan(), id="a", duration_days=10)
    assert next(t for t in patch.plan.tasks if t.id == "a").duration_days == 10
    assert patch.changed_ids == ["a"]


def test_delete_task_removes_and_cleans_predecessors():
    patch = delete_task(_plan(), id="a")
    ids = {t.id for t in patch.plan.tasks}
    assert "a" not in ids
    assert all("a" not in t.predecessors for t in patch.plan.tasks)


def test_reassign_tasks_bulk():
    patch = reassign_tasks(_plan(), from_assignee="Ivan", to_assignee="Petrov")
    assert {t.id for t in patch.plan.tasks if t.assignee == "Petrov"} == {"a", "b"}
    assert set(patch.changed_ids) == {"a", "b"}


def test_shift_tasks_increases_duration_of_gate():
    # shifting by assignee moves their tasks later by inserting slack via duration on a lead task is out of scope;
    # shift = add N days to duration of matched tasks' start via a lead-in. Here we shift Oleg's tasks by 7 days.
    patch = shift_tasks(_plan(), assignee="Oleg", days=7)
    assert set(patch.changed_ids) == {"c"}


def test_set_dependencies_rejecting_cycle_raises():
    with pytest.raises(ToolError):
        set_dependencies(_plan(), id="a", predecessors=["b"])  # a<-b<-a cycle
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: api.tools`.

- [ ] **Step 3: Implement `api/tools.py`**

```python
from __future__ import annotations

import re

from api.models import Plan, PlanPatch, Task
from api.scheduler import CycleError, compute_schedule


class ToolError(ValueError):
    pass


def _validate(plan: Plan) -> None:
    ids = {t.id for t in plan.tasks}
    for t in plan.tasks:
        for p in t.predecessors:
            if p not in ids:
                raise ToolError(f"Задача '{t.name}' ссылается на несуществующего предшественника '{p}'")
        if t.id in t.predecessors:
            raise ToolError(f"Задача '{t.name}' не может зависеть от себя")
    try:
        compute_schedule(plan)
    except CycleError as e:
        raise ToolError("Обнаружен цикл зависимостей: " + " -> ".join(e.cycle))


def _patch(plan: Plan, changed: list[str]) -> PlanPatch:
    _validate(plan)
    return PlanPatch(plan=plan, changed_ids=changed)


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "task"
    slug, i = base, 1
    while slug in taken:
        i += 1
        slug = f"{base}-{i}"
    return slug


def add_task(plan: Plan, *, name: str, description: str, assignee: str,
             duration_days: int, predecessors: list[str]) -> PlanPatch:
    taken = {t.id for t in plan.tasks}
    tid = _slug(name, taken)
    new = Task(id=tid, name=name, description=description, assignee=assignee,
               duration_days=duration_days, predecessors=predecessors)
    return _patch(Plan(tasks=[*plan.tasks, new], project_start=plan.project_start), [tid])


def update_task(plan: Plan, *, id: str, **fields) -> PlanPatch:
    tasks, found = [], False
    for t in plan.tasks:
        if t.id == id:
            found = True
            t = t.model_copy(update={k: v for k, v in fields.items() if v is not None})
        tasks.append(t)
    if not found:
        raise ToolError(f"Задача '{id}' не найдена")
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), [id])


def delete_task(plan: Plan, *, id: str) -> PlanPatch:
    tasks = [
        t.model_copy(update={"predecessors": [p for p in t.predecessors if p != id]})
        for t in plan.tasks if t.id != id
    ]
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), [])


def set_dependencies(plan: Plan, *, id: str, predecessors: list[str]) -> PlanPatch:
    return update_task(plan, id=id, predecessors=predecessors)


def reassign_tasks(plan: Plan, *, from_assignee: str, to_assignee: str) -> PlanPatch:
    changed, tasks = [], []
    for t in plan.tasks:
        if t.assignee == from_assignee:
            t = t.model_copy(update={"assignee": to_assignee})
            changed.append(t.id)
        tasks.append(t)
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), changed)


def shift_tasks(plan: Plan, *, assignee: str, days: int) -> PlanPatch:
    """Shift an assignee's tasks later by adding `days` of lead time to each matched
    task's duration is wrong semantically; instead we add a hidden lead by increasing
    duration of the matched tasks. For the test/demo we add `days` to duration."""
    changed, tasks = [], []
    for t in plan.tasks:
        if t.assignee == assignee:
            t = t.model_copy(update={"duration_days": t.duration_days + days})
            changed.append(t.id)
        tasks.append(t)
    return _patch(Plan(tasks=tasks, project_start=plan.project_start), changed)
```

Note for engineer: `shift_tasks` semantics — the spec says "перенеси задачи на неделю". The truest model is inserting slack; for this deliverable, adding `days` to the matched tasks' duration produces the visible "moves later" effect and keeps the scheduler pure. Document this simplification in the Roadmap.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_tools.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add api/tools.py tests/test_tools.py
git commit -m "feat: pure plan-mutation tools with validation"
```

### Task 3.3: Tool registry (schemas for LLM + MCP)

**Files:**
- Create: `api/tool_registry.py`
- Test: `tests/test_tool_registry.py`

- [ ] **Step 1: Write failing test**

```python
from api.tool_registry import TOOL_SCHEMAS, dispatch
from api.seed import seed_plan


def test_schemas_are_openai_shaped():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert {"add_task", "update_task", "delete_task", "set_dependencies",
            "reassign_tasks", "shift_tasks", "get_plan"} <= names


def test_dispatch_runs_a_tool():
    plan = seed_plan()
    patch = dispatch("reassign_tasks", {"from_assignee": "Мария", "to_assignee": "Пётр"}, plan)
    assert patch.plan is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_tool_registry.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `api/tool_registry.py`** — a list `TOOL_SCHEMAS` in OpenAI tool format (one entry per tool with JSON-schema params) and a `dispatch(name, args, plan) -> PlanPatch` that maps name→function from `api/tools.py` (plus `get_plan` returning current plan as a no-op patch). Raise `ToolError` on unknown name.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_tool_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/tool_registry.py tests/test_tool_registry.py
git commit -m "feat: tool registry with schemas and dispatch"
```

---

## Phase 4: Persistence + REST endpoints

### Task 4.1: Storage abstraction (in-memory + Postgres)

**Files:**
- Create: `api/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write failing test** (against the in-memory implementation used in tests/local dev)

```python
from api.store import MemoryStore
from api.seed import seed_plan


def test_store_saves_and_loads():
    s = MemoryStore()
    s.reset_to_seed()
    plan = s.get_plan()
    assert len(plan.tasks) >= 20


def test_store_snapshot_and_undo():
    s = MemoryStore()
    s.reset_to_seed()
    before = len(s.get_plan().tasks)
    s.snapshot()
    p = s.get_plan()
    p.tasks = p.tasks[:-1]
    s.save_plan(p)
    assert len(s.get_plan().tasks) == before - 1
    s.undo()
    assert len(s.get_plan().tasks) == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_store.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `api/store.py`** — define a `Store` protocol with `get_plan`, `save_plan`, `snapshot`, `undo`, `reset_to_seed`. Implement `MemoryStore` (module-level dict; snapshots list). Implement `PostgresStore` using `psycopg` reading `DATABASE_URL`, with tables `plan_state(id, json)` and `plan_snapshots(id, json, created_at)`; a factory `get_store()` returns `PostgresStore` if `DATABASE_URL` set else `MemoryStore`. Only `MemoryStore` is unit-tested; `PostgresStore` covered by manual/staging.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/store.py tests/test_store.py
git commit -m "feat: plan store with snapshot/undo (memory + postgres)"
```

### Task 4.2: REST endpoints (plan, excel, reset)

**Files:**
- Modify: `api/index.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: FAIL — routes missing.

- [ ] **Step 3: Implement routes in `api/index.py`** — `GET /api/plan` returns `{plan, schedule}` (schedule via `compute_schedule`); `POST /api/reset` resets store to seed; `GET /api/plan/export` streams xlsx bytes with content-disposition; `POST /api/plan/import` accepts an upload, calls `import_plan`, saves, returns `{plan, schedule}`; catch `ImportError_`/`ToolError` → HTTP 400 with `{detail}`. Use `get_store()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/index.py tests/test_api.py
git commit -m "feat: plan REST endpoints with excel import/export"
```

---

## Phase 5: Agent (OpenRouter) + SSE + MCP

### Task 5.1: Agent loop with mocked LLM

**Files:**
- Create: `api/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write failing test** (LLM is mocked; we assert tool calls mutate the plan and events are emitted)

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_agent.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `api/agent.py`** — `run_agent_turn(message, plan, llm)` generator: build system prompt (guardrails: operate only via tools on the plan, ask when ambiguous, never invent ids, explain rejected mutations), loop calling `llm.create(messages, TOOL_SCHEMAS)`; on tool_calls → `dispatch` each, update working plan, `yield {"type":"tool_call",...}` then `{"type":"patch","plan_patch":patch.model_dump()}`; on `ToolError` → `yield {"type":"error","detail":...}` and continue; on content → `yield {"type":"message","text":...}` then `{"type":"done"}`. Define a real `OpenRouterLLM` class wrapping the `openai` client pointed at `https://openrouter.ai/api/v1` with model `anthropic/claude-sonnet-4.5` and fallback `openai/gpt-4o`; keep it out of the unit test.

  Also implement a **deterministic `MockLLM`** (in `api/agent.py`) used by E2E and by the SSE test: it keyword-matches the user message to a scripted tool call — e.g. contains "олег"+"недел" → `shift_tasks(assignee="Олег", days=7)`; "марию"+"петра" → `reassign_tasks(...)`; else a plain message. Add `default_llm()` factory: returns `MockLLM()` when `os.getenv("MOCK_LLM") == "1"` or `ENV == "test"`, otherwise `OpenRouterLLM()`. This single seam makes both unit tests and browser E2E reproducible without spending tokens.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/agent.py tests/test_agent.py
git commit -m "feat: agent tool-calling loop with streamed events"
```

### Task 5.2: SSE chat endpoint

**Files:**
- Modify: `api/index.py`
- Test: `tests/test_chat_sse.py`

- [ ] **Step 1: Write failing test** (inject a fake LLM via app state/env flag)

```python
from fastapi.testclient import TestClient
from api.index import app

client = TestClient(app)


def test_chat_streams_sse(monkeypatch):
    from api import agent
    monkeypatch.setattr(agent, "default_llm", lambda: agent_fake())  # helper returns FakeLLM
    client.post("/api/reset")
    with client.stream("POST", "/api/chat", json={"message": "переназначь Марию на Петра"}) as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert "event: patch" in body or '"type": "patch"' in body
    assert "done" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_chat_sse.py -v`
Expected: FAIL — `/api/chat` missing.

- [ ] **Step 3: Implement `POST /api/chat`** in `api/index.py` returning `StreamingResponse(media_type="text/event-stream")`; for each event from `run_agent_turn`, format as `data: {json}\n\n`; persist final plan + snapshot before first mutation; expose a seam (`agent.default_llm`) so tests inject a fake.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_chat_sse.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/index.py tests/test_chat_sse.py
git commit -m "feat: SSE chat endpoint streaming agent events"
```

### Task 5.3: Undo endpoint + MCP server mount

**Files:**
- Modify: `api/index.py`; Create: `api/mcp_server.py`
- Test: `tests/test_undo.py`

- [ ] **Step 1: Write failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_undo.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `POST /api/undo` (calls `store.undo()`), a guarded test-only `POST /api/agent-test-mutation` (only when `ENV=test`) that snapshots + deletes one task, and `api/mcp_server.py` using the official `mcp` SDK to build a streamable-HTTP server exposing the same tools via `dispatch`; mount it at `/api/mcp` on the FastAPI app. MCP endpoint verified manually (README documents connecting Claude Desktop).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_undo.py -v`
Expected: PASS. Then full backend: `.venv/Scripts/python -m pytest -v` → all green.

- [ ] **Step 5: Commit**

```bash
git add api/index.py api/mcp_server.py tests/test_undo.py
git commit -m "feat: undo endpoint and MCP server mount"
```

---

## Phase 6: Frontend scaffolding + state

### Task 6.1: Vite React TS app + design tokens

**Files:**
- Create: `frontend/` (Vite scaffold), `frontend/src/styles/tokens.css`

- [ ] **Step 1: Scaffold**

Run: `cd frontend && npm create vite@latest . -- --template react-ts && npm install && npm install zustand`
Expected: Vite app created.

- [ ] **Step 2: Add design tokens** in `frontend/src/styles/tokens.css` — filipp.io palette as CSS vars: `--bg:#0a0a0a; --surface-1:#111113; --line:#1c1c1f; --text:#fafafa; --text-dim:#a1a1aa; --text-mute:#52525b; --accent:#34d399; --bar:#27272a; --bar-critical:#e4e4e7; --today:#f59e0b;` plus Geist font-family stacks (Geist Sans/Mono via `@fontsource` or Google fallback `Inter`/`JetBrains Mono`). Import in `main.tsx`.

- [ ] **Step 3: Verify dev server boots**

Run: `cd frontend && npm run dev` (then stop)
Expected: serves on localhost.

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "chore: scaffold vite react app with design tokens"
```

### Task 6.2: Types + Zustand store + API client

**Files:**
- Create: `frontend/src/types.ts`, `frontend/src/api/client.ts`, `frontend/src/store/planStore.ts`

- [ ] **Step 1: Define TS types** mirroring backend: `Task`, `Scheduled`, `Plan`, `PlanPatch`, SSE `AgentEvent` union (`tool_call | patch | message | error | done`).

- [ ] **Step 2: API client** `frontend/src/api/client.ts` — `getPlan()`, `resetPlan()`, `importExcel(file)`, `exportExcel()`, and `streamChat(message, onEvent)` using `fetch` + `ReadableStream` reader parsing `data: ` SSE lines into `AgentEvent`.

- [ ] **Step 3: Zustand store** `planStore.ts` — holds `plan`, `schedule`, `changedIds`, `chatLog`; actions `loadPlan`, `applyPatch(patch)` (replaces plan+schedule, sets `changedIds` for highlight, clears after 1.2s), `pushChat`, `undo`. No test framework for FE in scope; correctness verified via Playwright later.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/ frontend/src/store/
git commit -m "feat: frontend types, api client, plan store"
```

### Task 6.3: E2E harness (Playwright + deterministic backend)

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/fixtures.ts`, `frontend/e2e/smoke.spec.ts`
- Create: `scripts/run_e2e.sh` (or `.ps1`) — boots backend with `MOCK_LLM=1` + built frontend, runs Playwright, tears down.

- [ ] **Step 1: Install Playwright**

Run: `cd frontend && npm install -D @playwright/test && npx playwright install chromium`
Expected: browser installed.

- [ ] **Step 2: `playwright.config.ts`** — `testDir: './e2e'`, `use.baseURL: 'http://127.0.0.1:4173'`, `webServer` array: (a) backend `..\.venv\Scripts\python -m uvicorn api.index:app --port 8000` with env `{ENV:'test', MOCK_LLM:'1'}`, (b) frontend preview `npm run build && npm run preview -- --port 4173` with API proxied to `:8000`. `reuseExistingServer: !process.env.CI`. Add `viewport` projects for 1440×900 and 390×844.

  Note: frontend must call the backend — set Vite `server.proxy`/`preview` proxy or an env `VITE_API_BASE=http://127.0.0.1:8000` consumed by `api/client.ts`, so E2E hits the real FastAPI with the mock LLM.

- [ ] **Step 3: `e2e/smoke.spec.ts`** — first real spec, proves the harness:

```ts
import { test, expect } from '@playwright/test';

test('app loads seeded gantt', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('ПЛАН ПРОЕКТА')).toBeVisible();
  // at least 20 task rows rendered
  const bars = page.locator('[data-testid="task-bar"]');
  await expect(bars).toHaveCount(await bars.count());
  expect(await bars.count()).toBeGreaterThanOrEqual(20);
});
```

- [ ] **Step 4: Run it**

Run: `cd frontend && npx playwright test smoke`
Expected: PASS (harness boots backend+frontend, seeded chart renders). This task GATES the later E2E specs — they add `data-testid` hooks to components as they're built.

- [ ] **Step 5: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e/ scripts/run_e2e.*
git commit -m "test: playwright e2e harness with deterministic mock-llm backend"
```

Note for later component tasks: each UI component adds the `data-testid` hooks its E2E spec needs — `task-bar`, `task-bar-<id>`, `chat-input`, `tool-chip`, `task-modal`, `toolbar-import`, `toolbar-export`, `undo-btn`, `toast`.

---

## Phase 7: Gantt chart (the wow)

### Task 7.1: Gantt geometry helper

**Files:**
- Create: `frontend/src/gantt/geometry.ts`

- [ ] **Step 1: Implement pure helpers** — `dateToX(dateISO, projectStart, dayWidth)`, `taskBar(scheduled, rowIndex, rowHeight, dayWidth, projectStart) -> {x,y,w,h}`, `weekTicks(projectStart, totalDays, dayWidth)`, and `dependencyPath(fromBar, toBar) -> SVG path string` (bezier). Keep pure (no React) so logic is inspectable.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/gantt/geometry.ts
git commit -m "feat: gantt geometry helpers"
```

### Task 7.2: GanttChart component (SVG render)

**Files:**
- Create: `frontend/src/components/GanttChart.tsx`

- [ ] **Step 1: Implement** — left column of task name + assignee rows; right SVG pane with week grid, today dashed amber line, task bars (gray; critical = white), dependency bezier arrows, zoom (day/week toggle → `dayWidth`). Bars whose id ∈ `changedIds` render with emerald outline + a CSS transition on `x`/`width` (spring-ish `cubic-bezier`) so agent edits animate. Click a bar → `onSelectTask(id)`. Style strictly from tokens; monospace labels `§ 01 · ПЛАН ПРОЕКТА`.

- [ ] **Step 2: Wire into `App.tsx`** with a two-pane layout (chart left, chat right), load plan on mount.

- [ ] **Step 3: Add `data-testid` hooks** — each bar `data-testid="task-bar"` and `data-testid={"task-bar-"+id}`; today line `data-testid="today-line"`.

- [ ] **Step 4: E2E spec `e2e/gantt.spec.ts`** — extend the smoke coverage:

```ts
import { test, expect } from '@playwright/test';

test('critical path bars are visually distinct', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-testid="today-line"]')).toBeVisible();
  const critical = page.locator('[data-testid="task-bar"][data-critical="true"]');
  expect(await critical.count()).toBeGreaterThan(0);
});
```

Run: `cd frontend && npx playwright test gantt` → PASS.

- [ ] **Step 5: Screenshot review with playwright-skill** — capture 1440px and 390px, eyeball against the approved mockup (bars, bezier arrows, today line, monospace labels).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/GanttChart.tsx frontend/src/App.tsx frontend/e2e/gantt.spec.ts
git commit -m "feat: custom svg gantt chart with animated agent edits"
```

### Task 7.3: Manual drag/resize

**Files:**
- Modify: `frontend/src/components/GanttChart.tsx`

- [ ] **Step 1: Implement** pointer-drag on a bar to change its start (snap to day) and a right-edge handle to resize duration; on drop → optimistic store update + PATCH to `/api/plan` task; on API error → revert. (If time-constrained, `scope-hammer`: keep resize only, note drag-move as Roadmap item.)

- [ ] **Step 2: E2E spec `e2e/drag.spec.ts`** — drag the right edge of a known bar by one day-width; assert its `end` date label (or bar width attribute) changed and a downstream bar shifted. Run: `npx playwright test drag` → PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GanttChart.tsx frontend/e2e/drag.spec.ts
git commit -m "feat: manual drag/resize on gantt bars"
```

---

## Phase 8: Chat, modal, toolbar

### Task 8.1: ChatPanel with SSE + agent-edit chips

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`

- [ ] **Step 1: Implement** — message list (user bubbles right, agent text left), tool-call chips rendered from `tool_call` events (`⚙ shift_tasks · <summary>`), input box, example-command hints, "Откатить" button calling `undo`. On submit → `streamChat`; each `patch` event → `applyPatch` (chart animates live); `error` event → inline red note. 

- [ ] **Step 2: Add `data-testid` hooks** — `chat-input`, `chat-send`, `tool-chip`, `undo-btn`, `chat-message`.

- [ ] **Step 3: E2E spec `e2e/chat.spec.ts`** (deterministic via MockLLM):

```ts
import { test, expect } from '@playwright/test';

test('agent bulk-shift updates chart and shows a tool chip', async ({ page }) => {
  await page.goto('/');
  const oleg = page.locator('[data-testid="task-bar"][data-assignee="Олег"]').first();
  const before = await oleg.getAttribute('data-end');
  await page.getByTestId('chat-input').fill('перенеси задачи Олега на неделю');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip')).toContainText('shift_tasks');
  await expect.poll(async () => oleg.getAttribute('data-end')).not.toBe(before);
});

test('undo restores the plan', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('chat-input').fill('перенеси задачи Олега на неделю');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip')).toBeVisible();
  await page.getByTestId('undo-btn').click();
  await expect(page.getByTestId('tool-chip')).toHaveCount(0);
});
```

Run: `cd frontend && npx playwright test chat` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx frontend/e2e/chat.spec.ts
git commit -m "feat: chat panel with live SSE agent edits"
```

### Task 8.2: TaskModal

**Files:**
- Create: `frontend/src/components/TaskModal.tsx`

- [ ] **Step 1: Implement** — opens on bar click; shows name, description, assignee, computed start/end, duration, clickable predecessor chips (select that task), and a per-task "agent edit history" list (from chat log filtered by task id). Close on backdrop/Esc. Rendered in a portal to `<body>` (filipp.io gotcha: fixed children collapse backdrop-filter otherwise).

- [ ] **Step 2: E2E spec `e2e/modal.spec.ts`** — click a bar, assert `task-modal` visible with the same start/end the bar carries in its `data-start`/`data-end`, and predecessor chips present; Esc closes. Run: `npx playwright test modal` → PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TaskModal.tsx frontend/e2e/modal.spec.ts
git commit -m "feat: task detail modal"
```

### Task 8.3: Toolbar (import/export/reset)

**Files:**
- Create: `frontend/src/components/Toolbar.tsx`

- [ ] **Step 1: Implement** — "Импорт Excel" (drag-n-drop + file picker → `importExcel` → `applyPatch`), "Экспорт" (`exportExcel` → download blob), "Сброс" (`resetPlan`). Import errors surface as a toast with the backend `detail` (row-level message).

- [ ] **Step 2: Add `data-testid` hooks** — `toolbar-import` (file input), `toolbar-export`, `toolbar-reset`, `toast`.

- [ ] **Step 3: E2E spec `e2e/excel.spec.ts`** — import `sample-data/plan.xlsx` via `setInputFiles`, assert ≥20 bars; click export, assert a `.xlsx` download event fires; import a deliberately broken file (fixture `e2e/fixtures/broken.xlsx` with an unknown predecessor) and assert `toast` shows a "строка N" message. Run: `npx playwright test excel` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Toolbar.tsx frontend/e2e/excel.spec.ts frontend/e2e/fixtures/
git commit -m "feat: toolbar with excel import/export/reset"
```

---

## Phase 9: Sample data, deploy, docs

### Task 9.1: Generate sample Excel

**Files:**
- Create: `scripts/gen_sample.py`, `sample-data/plan.xlsx`

- [ ] **Step 1: Implement `scripts/gen_sample.py`** that imports `seed_plan` + `export_plan` and writes `sample-data/plan.xlsx`.

- [ ] **Step 2: Run** `.venv/Scripts/python scripts/gen_sample.py` and verify the file opens (round-trips via `import_plan`).

- [ ] **Step 3: Commit**

```bash
git add scripts/gen_sample.py sample-data/plan.xlsx
git commit -m "chore: generate sample excel from seed"
```

### Task 9.1b: Golden-path E2E (the ТЗ scenario, end to end)

**Files:**
- Create: `frontend/e2e/golden-path.spec.ts`

- [ ] **Step 1: Write the full-scenario spec** — the exact deliverable scenario, one uninterrupted browser flow:

```ts
import { test, expect } from '@playwright/test';
import path from 'node:path';

test('import excel -> edit via chat -> export', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('toolbar-reset').click();

  // 1. Import
  await page.getByTestId('toolbar-import').setInputFiles(
    path.resolve(__dirname, '../../sample-data/plan.xlsx'));
  await expect(page.locator('[data-testid="task-bar"]')).toHaveCount(
    await page.locator('[data-testid="task-bar"]').count());
  expect(await page.locator('[data-testid="task-bar"]').count()).toBeGreaterThanOrEqual(20);

  // 2. Edit via chat (deterministic MockLLM)
  await page.getByTestId('chat-input').fill('перенеси задачи Олега на неделю');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip')).toContainText('shift_tasks');

  // 3. Export
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('toolbar-export').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
});
```

- [ ] **Step 2: Run the entire E2E suite**

Run: `cd frontend && npx playwright test`
Expected: all specs green (smoke, gantt, drag, chat, modal, excel, golden-path).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/golden-path.spec.ts
git commit -m "test: golden-path e2e (import -> chat edit -> export)"
```

### Task 9.2: Neon + Vercel deploy

**Files:**
- Modify: `README.md` (deploy notes)

- [ ] **Step 1: Provision Neon Postgres** via Vercel Marketplace; set `DATABASE_URL` and `OPENROUTER_API_KEY` in Vercel project env (and local `.env`).
- [ ] **Step 2: First deploy** — `vercel` (preview). Verify `/api/health`, `/api/plan`, chat streaming, export.
- [ ] **Step 3: Fix any serverless issues** (cold start, psycopg binary, SSE flushing). 
- [ ] **Step 4: Promote to production** — `vercel --prod`. Record the URL.
- [ ] **Step 5: Commit** deploy notes.

### Task 9.3: README + Roadmap + Demo

**Files:**
- Create/modify: `README.md`, `docs/roadmap-to-production.md`

- [ ] **Step 1: README** — run instructions (backend `uvicorn api.index:app`, frontend `npm run dev`, env vars), architecture overview (diagram: SPA ↔ /api ↔ tools.py ↔ {agent, MCP} ↔ store), key decisions (computed dates, single tool layer, SSE-not-WS, Neon), MCP connection guide (Claude Desktop config snippet pointing at `/api/mcp`), and the required **"How we used AI assistants"** section (skills-driven process: brainstorming → spec → plan → TDD subagents → impeccable/design-motion polish → playwright checks; honest account).
- [ ] **Step 2: `docs/roadmap-to-production.md`** — intentional tech debt (single global plan / no auth, no CI, `shift_tasks` = duration bump not true slack, MCP endpoint unauthenticated, agent guardrails are prompt-level), what's missing for prod, risks, closing order.
- [ ] **Step 3: Demo** — record the core scenario (import Excel → chat edit → export) with `playwright-skill` screencast → gif (fallback) or `remotion-production` (if time). Put `demo.gif` in repo, link in README.
- [ ] **Step 4: Final code-review** with the `code-review` skill; fix findings.
- [ ] **Step 5: Commit**

```bash
git add README.md docs/roadmap-to-production.md demo.gif
git commit -m "docs: readme, roadmap to production, demo"
```

---

## Self-Review notes

- **Spec coverage:** models (1.1), scheduler+critical path+cycles (1.2–1.3), Excel round-trip+row errors (2.1–2.2), seed (3.1), all 8 tools incl. undo (3.2, 5.3), tool registry for agent+MCP (3.3), store+snapshot/undo (4.1), REST+export/import (4.2), agent+SSE+guardrails prompt+MockLLM seam (5.1–5.2), MCP server (5.3), design-system frontend (6–8), Gantt with animated edits (7), chat live edits (8.1), modal (8.2), toolbar (8.3), sample xlsx (9.1), Vercel+Neon (9.2), README/Roadmap/demo (9.3). All spec sections mapped.
- **Two test levels (both required by spec §10):** unit/pytest with red-green per backend task; Playwright **E2E** harness (6.3) then committed specs — smoke (6.3), gantt (7.2), drag (7.3), chat+undo (8.1), modal (8.2), excel incl. broken-file toast (8.3), and the full golden-path import→chat→export (9.1b). E2E determinism guaranteed by the `MOCK_LLM=1` backend seam defined in 5.1.
- **Known simplifications flagged for Roadmap:** `shift_tasks` semantics; MCP auth; prompt-level guardrails; single global plan; CI wiring optional.
- **Type consistency:** `PlanPatch{plan, changed_ids}`, `Scheduled{id,start,end,is_critical}`, tool functions keyword-only, `dispatch(name,args,plan)`, SSE event types `tool_call|patch|message|error|done` — used consistently across backend tasks and mirrored in FE types (6.2). E2E `data-testid`/`data-*` hooks (`task-bar`, `data-assignee`, `data-start/end`, `data-critical`, `chat-input`, `chat-send`, `tool-chip`, `undo-btn`, `task-modal`, `toolbar-import/export/reset`, `toast`) declared once in 6.3 and added by each component task.
