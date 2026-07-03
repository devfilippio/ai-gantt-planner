# AI Gantt Planner

An AI-native project planning tool: a live, interactive Gantt chart that you edit in bulk by talking to it — "move Oleg's tasks a week later," "reassign Maria's work to Petr" — and the bars animate on screen as the agent applies the change. Import/export Excel, undo any agent edit, and the same mutation layer is exposed over MCP so any MCP-compatible client (Claude Desktop, Cursor, etc.) can drive the plan too.

<!-- LIVE URL: to be filled after deploy -->

![Demo: import Excel, edit via chat, export](docs/demo.gif)

More screenshots: [`docs/shots/`](docs/shots/).

---

## Quickstart

### Backend (FastAPI)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pip install pytest httpx   # dev/test only

# deterministic mode (no LLM calls, no API key needed)
MOCK_LLM=1 .venv/Scripts/python -m uvicorn api.index:app --reload --port 8000
```

> **Windows note:** `.python-version` declares `3.13`, but the checked-in `.venv` was built with the **Python 3.12** available on the dev machine (`.venv/Scripts/python --version` → `3.12.10`). Everything works on 3.12+; if you recreate the venv and have 3.13 installed, either is fine.

Backend env vars (`.env`, gitignored):

| Var | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | for real chat | OpenRouter key for the LLM agent (`anthropic/claude-sonnet-4.5`, fallback `openai/gpt-4o`) |
| `DATABASE_URL` | optional | Neon/Postgres connection string. Omit it and the app runs on an in-memory store (fine for local dev/demo; state resets on restart) |
| `MOCK_LLM=1` | optional | Forces a deterministic keyword-matched fake LLM instead of a real API call — used by tests and E2E, also handy for local dev without spending tokens |
| `ENV=test` | optional | Also switches to the mock LLM, and unlocks the test-only `/api/agent-test-mutation` route used by the undo test |

### Frontend (Vite + React + TS)

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, proxies /api to :8000
```

Point the frontend at a non-default backend with `VITE_API_BASE` (used by the Playwright harness to hit `127.0.0.1:8000` directly against the preview build).

---

## Architecture

Monorepo, single Vercel project, one deployed URL. The SPA and the API are both served from the same domain — the SPA calls `/api/*`, Vercel rewrites those to the single FastAPI ASGI app in `api/index.py`.

```
                         ┌────────────────────────────┐
                         │        Vercel (1 project)   │
                         │                              │
   Browser  ── /  ──────▶│  Vite SPA (frontend/dist)   │
                         │                              │
   Browser  ── /api/* ──▶│  api/index.py (FastAPI)      │
                         │        │                      │
                         │        ▼                      │
                         │   api/tools.py  (single       │
                         │   plan-mutation tool layer)   │
                         │     │              │           │
                         │     ▼              ▼           │
                         │  internal agent   MCP server   │
                         │  (SSE /api/chat)  (/api/mcp)    │
                         │     │                            │
                         │     ▼                            │
                         │  api/store.py → Neon Postgres    │
                         │  (or in-memory for local dev)    │
                         └────────────────────────────┘
```

- **`api/scheduler.py`** — pure function `compute_schedule(plan)`. Dates are **never stored**; every task has only a `duration_days` and `predecessors`, and start/end are computed on every read via topological sort (`start = max(end of predecessors)`, `end = start + duration`). Cycles raise `CycleError`; the critical path is flagged by walking backward from the tasks that end at the project's latest date.
- **`api/tools.py`** — the one place plan mutations happen: `add_task`, `update_task`, `delete_task`, `set_dependencies`, `reassign_tasks`, `shift_tasks`. Pure functions: `Plan` in, `PlanPatch` (`{plan, changed_ids}`) out, validated (no dangling predecessors, no cycles) before returning.
- **`api/tool_registry.py`** — OpenAI-style JSON-schema wrappers around the tools above, plus `dispatch(name, args, plan)`. This registry is consumed by **both** the internal agent and the MCP server, so there is exactly one definition of what a "tool" does — no drift between the two integration surfaces.
- **`api/agent.py`** — the chat agent's tool-calling loop (`run_agent_turn`). Streams `tool_call` → `patch` → `message` → `done` events. LLM access is behind a tiny `LLM` protocol with three implementations: `OpenRouterLLM` (real, `anthropic/claude-sonnet-4.5` → falls back to `openai/gpt-4o` on error), `MockLLM` (deterministic keyword matcher), and `default_llm()` which picks `MockLLM` whenever `MOCK_LLM=1` or `ENV=test`.
- **`api/mcp_server.py`** — a real MCP server (official `mcp` Python SDK, `FastMCP`, streamable-HTTP transport, `stateless_http=True`), mounted as an ASGI sub-app at `/api/mcp`. Stateless because Vercel serverless functions don't guarantee two requests land on the same instance — there is no server-side MCP session to keep alive between calls.
- **`api/store.py`** — a `Store` protocol with two implementations: `MemoryStore` (dict + snapshot list, used in tests and default local dev) and `PostgresStore` (Neon, via `psycopg`, JSONB columns for plan state + snapshot history). `get_store()` picks Postgres when `DATABASE_URL` is set, else memory. Undo is a snapshot stack: every mutating request snapshots the plan before applying the first change, and `POST /api/undo` pops the latest snapshot back into place.
- **Frontend** — Vite + React 19 + TypeScript + Zustand. The Gantt chart is hand-built SVG (no charting library): a left column of task/assignee rows and a right SVG pane with a week grid, a dashed "today" line, dependency bezier arrows, and bars that animate (CSS transition on `x`/`width`) whenever their id appears in an SSE `patch` event's `changed_ids`, with a fading emerald highlight.

### Key decisions

- **Custom SVG Gantt, not a charting library.** Full control over the "bars glide to their new position while a chip appears in chat" moment — the actual point of the product — which off-the-shelf Gantt components don't animate the way this needed.
- **Computed dates, not stored dates.** A task only has a duration and predecessors; start/end are derived. This makes every mutation (reassign, shift, add, delete) trivially consistent — there is no "recompute the whole schedule and hope nothing drifted" step, because nothing is ever stored that could drift.
- **One tool layer for both surfaces.** `api/tools.py` + `api/tool_registry.py` are consumed identically by the chat agent and by the MCP server. Adding a new capability means writing one function once; both an end-user chatting in the UI and a developer's MCP client (Claude Desktop, Cursor, etc.) get it automatically and with the same validation.
- **SSE, not WebSocket.** Vercel's serverless Python runtime supports streaming HTTP responses; it does not give you a persistent bidirectional socket. `POST /api/chat` streams newline-delimited SSE events, which is exactly the shape this needs (server → client only, one request per chat turn) and deploys without extra infrastructure.
- **A deterministic `MockLLM` seam.** `default_llm()` swaps in a keyword-matching fake whenever `MOCK_LLM=1` or `ENV=test`. Every unit test and every Playwright E2E spec (including the golden path and the recorded demo) runs against this — no flakiness from a real model's non-determinism, no API spend for CI, and the same code path the real `OpenRouterLLM` runs through end to end.

---

## MCP

The plan-mutation tools are exposed as a standards-compliant MCP server (streamable-HTTP transport) at:

```
/api/mcp/          ← note the trailing slash; FastMCP mounts at exactly this path
```

Exposed tools: `get_plan`, `add_task`, `update_task`, `delete_task`, `set_dependencies`, `reassign_tasks`, `shift_tasks`. Each mutating tool loads the current plan from the shared store, applies the change through the same validated `api/tools.py` functions the chat agent uses, persists the result, and returns a short text summary (changed task ids + total task count). Validation errors (bad id, dependency cycle, etc.) come back as a normal tool result (`"Ошибка: ..."`) rather than a crash.

### Connecting a client

Local dev:

```json
{
  "mcpServers": {
    "ai-gantt-planner": {
      "url": "http://127.0.0.1:8000/api/mcp/"
    }
  }
}
```

Against the deployed app (Claude Desktop, `claude_desktop_config.json`, or any MCP client that speaks streamable-HTTP):

```json
{
  "mcpServers": {
    "ai-gantt-planner": {
      "url": "https://<your-deployed-domain>/api/mcp/"
    }
  }
}
```

The server is **stateless** by design (`stateless_http=True`) — no session affinity is required between requests, which matches how Vercel serverless functions are invoked. See [`docs/roadmap-to-production.md`](docs/roadmap-to-production.md) for the known gap that this endpoint is currently unauthenticated.

---

## Testing

**Unit tests (pytest, 32 tests)** — models, scheduler (date computation, cycle detection, critical path), Excel import/export round-trip with row-level error messages, seed data, tools, tool registry, store (memory), REST endpoints, the agent loop (with a fake LLM), the SSE chat endpoint, undo, and the MCP tool dispatch:

```bash
ENV=test MOCK_LLM=1 .venv/Scripts/python -m pytest -q
```

**End-to-end (Playwright, desktop + mobile viewports)** — boots the real FastAPI backend with `MOCK_LLM=1` and the built frontend, then drives a real browser against both:

```bash
cd frontend
npx playwright test --project=desktop
```

Specs:

| Spec | Covers |
|---|---|
| `smoke.spec.ts` | App loads, seeded plan renders ≥20 bars |
| `gantt.spec.ts` | Critical-path bars are visually distinct, today-line renders |
| `drag.spec.ts` | Dragging a bar's right edge resizes duration and shifts downstream tasks |
| `chat.spec.ts` | Chat agent bulk-edits the plan live and shows a tool-call chip; undo reverts it |
| `modal.spec.ts` | Task detail modal shows matching dates and predecessor chips |
| `excel.spec.ts` | Import renders ≥20 bars, export triggers an `.xlsx` download, a broken file surfaces a row-level toast |
| **`golden-path.spec.ts`** | The full deliverable scenario in one uninterrupted flow: reset → import → chat edit → export |
| `demo.spec.ts` | Same scenario, slowed down deliberately and recorded on video (see [Demo](#demo)) |

Both viewport projects (`desktop` 1440×900, `mobile` 390×844) exist in `frontend/playwright.config.ts`; a third project, `demo-recording`, only matches `demo.spec.ts` and turns video recording on.

**Determinism note:** every E2E spec runs against the backend started with `MOCK_LLM=1`. `MockLLM` keyword-matches the chat message (e.g. "Олег" + "недел" → `shift_tasks(assignee="Олег", days=7)`) instead of calling a real model, so results are exactly reproducible run to run — no network flakiness, no token spend, no risk of a model changing its mind about which tool to call between CI runs.

---

## Demo

![Demo gif](docs/demo.gif)

Recorded via a scripted Playwright spec (`frontend/e2e/demo.spec.ts`) against the real app with the deterministic `MockLLM` backend, converted from the captured `.webm` with:

```bash
ffmpeg -i video.webm -vf "fps=12,scale=1000:-1:flags=lanczos" docs/demo.gif
```

Static screenshots are in [`docs/shots/`](docs/shots/) (seeded Gantt chart, a live chat-driven edit).

---

## How we used AI assistants

This project was built end-to-end with **Claude Code**, using a skills-driven workflow rather than one long unstructured chat:

1. **Brainstorming** — the product shape (Gantt + chat agent + Excel + MCP, Vercel-deployed) was explored and locked down before any code, including the visual direction (a dark, editorial, filipp.io-inspired aesthetic) and the approved mockup layout.
2. **Spec → plan** — the brainstormed decisions were turned into a written design spec, then a detailed, phase-by-phase implementation plan (`docs/superpowers/plans/2026-07-03-ai-gantt-planner.md`) with explicit red/green TDD steps for every backend module and E2E coverage requirements for every frontend component, before implementation started.
3. **Subagent-driven TDD execution** — the plan was executed task by task: write a failing test, run it, implement the minimal code to pass, run it again, commit. This applies to every backend module (scheduler, Excel import/export, tools, tool registry, store, agent, endpoints) and is why the commit history reads as small, reviewable, test-then-implementation steps.
4. **Design skills for the frontend** — UI work went through `frontend-design`, then a dedicated polish/audit pass (`impeccable`) and a motion-specific review (`design-motion`) to catch generic "AI-slop" patterns and make sure the agent-edit animation (the actual wow-moment of the product) reads as intentional, not accidental.
5. **Playwright verification, not eyeballing** — every interactive behavior (drag-resize, chat-driven bulk edits, undo, import/export, modal) has a Playwright spec that runs against the real backend and a real (Chromium) browser, not just unit tests of isolated logic. The golden-path and demo specs additionally exercise the exact end-to-end scenario a reviewer would run by hand.
6. **Phase-by-phase self-review** — each phase of the plan ends with running the full test suite (unit + E2E) before moving on, and the plan document itself carries a "Self-Review notes" section mapping every spec requirement to the task that implements it, so nothing from the original ask silently fell off scope.

In short: Claude Code did the typing, but the sequencing — decide, spec, plan, test-first implement, design-review, verify — was deliberate and is visible in both the git history and the `docs/superpowers/` artifacts checked into this repo.

---

## Repo layout

```
api/            FastAPI backend (models, scheduler, excel, tools, agent, store, mcp_server, index)
frontend/       Vite + React + TS SPA, Playwright E2E specs under frontend/e2e/
tests/          pytest suite (mirrors api/ modules)
sample-data/    plan.xlsx — a ready-to-import 27-task sample plan (generated by scripts/gen_sample.py)
docs/           roadmap-to-production.md, demo.gif, screenshots, planning artifacts
vercel.json     single-project routing: /api/* -> api/index.py, everything else -> the SPA
```

See [`docs/roadmap-to-production.md`](docs/roadmap-to-production.md) for known gaps, intentional shortcuts, and the order they'd get closed in before a real production launch.
