# Roadmap to production

This project is a test-task/demo build: fully tested (49 backend unit tests, 14 Playwright E2E specs across desktop + a recorded demo project), but deliberately scoped down in places to fit the appetite. This document is the honest account of what's cut, why, and what order to close the gaps in before this could carry real users or real money.

## Intentional tech debt (cut on purpose, with a known cost)

1. **FIXED — `shift_tasks` now performs a true shift.** `Task` gained a `lead_days` field (extra calendar days to wait before a task can start, applied after the later of predecessors'-end / project-start — see `api/models.py`, `api/scheduler.py::compute_schedule`). `shift_tasks` (`api/tools.py`) now adjusts `lead_days` instead of `duration_days`, so "move Oleg's tasks a week later" pushes the start (and therefore the end) date without lengthening the task — effort is preserved. Negative `days` moves tasks earlier, clamped at `lead_days >= 0`. `add_task`/`update_task` also accept an explicit `start_date` (YYYY-MM-DD), which resolves to the equivalent `lead_days` against the task's natural start (max of predecessors' ends, or project start) — this is also what unblocked giving an independent task (no predecessors) a specific calendar start date, which was previously impossible since dates were always `project_start` for a root task.
2. **Single global plan, no multi-user, no auth.** There is exactly one plan in the store (`_SINGLETON_ID = 1` in `api/store.py`), shared by every visitor. There's no concept of a project, a user, or an ownership boundary. Fine for a single-reviewer demo; not fine the moment two people open the app at once.
3. **MCP endpoint (`/api/mcp`) is unauthenticated.** Anyone who can reach the deployed URL can mutate the plan via MCP with no credential at all. Needs a bearer token (or mTLS/IP allowlist for an internal tool) checked before `dispatch()` runs.
4. **Agent guardrails are prompt-level only.** `api/agent.py`'s `SYSTEM_PROMPT` tells the model not to invent task ids, to ask when ambiguous, and to explain rejected mutations — but nothing enforces this outside the model's own compliance. A jailbroken or confused model could still emit an `arguments` payload that passes `dispatch`'s schema check but is semantically wrong (e.g., a wildly large `duration_days`). There is no server-side allowlist of "safe" argument ranges, no rate limiting on tool calls per turn beyond `MAX_TURNS = 6`, and no output-side check that the natural-language `message` event matches what actually happened.
5. **No CI pipeline wired up.** Both suites (pytest, Playwright) exist and pass locally; nothing runs them automatically on push/PR yet. See the sample workflow below.
6. **Drag-move is not implemented — only resize.** Task 7.3 of the plan called out drag/resize; `frontend/src/components/GanttChart.tsx` + `e2e/drag.spec.ts` cover dragging the right edge to change duration, but dragging the whole bar to change its start date (independent of predecessors) is not implemented. The backend now has the `lead_days` field needed to support this (see item 1) — dragging a whole bar just needs to be wired to a `PATCH .../task/{id}` call setting `start_date`/`lead_days` instead of `duration_days`; not done yet.
7. **`PostgresStore` undo semantics are only manually tested.** `tests/test_store.py` only exercises `MemoryStore`. `PostgresStore`'s snapshot/undo (`api/store.py`) uses the same logic shape but has never run against a real Neon instance in an automated test — first real traffic against Postgres is effectively the first test of that code path.
8. **Mobile drag is skipped.** The Playwright config has a `mobile` project (390×844) and `smoke`/`gantt`/`chat`/`excel`/`modal` all run there, but `drag.spec.ts` and the pointer-based resize interaction were built and verified for desktop pointer events only; touch-drag on the Gantt bars is unverified.
9. **Observability, rate limiting, and error tracking are entirely absent.** No Sentry/equivalent, no request logging beyond FastAPI's defaults, no rate limit on `/api/chat` (each call may invoke a real paid LLM), no metrics on tool-call success/failure rates or agent turn counts.
10. **Excel import/export does not carry `lead_days`.** The required 5-column format (задача, описание, исполнитель, длительность, предшественники) is unchanged by design — a task's `lead_days` (custom start date / true shift) is not written on export and not read on import, so round-tripping through Excel silently resets any lead time to 0.

## What's still missing before "real" production

- **Cold-start latency of the MCP session manager on serverless.** `api/index.py`'s `lifespan` starts `mcp.session_manager.run()` for the whole app on every cold start, before any request (including unrelated ones like `/api/health`) can be served. On Vercel's Python runtime this adds to the cold-start tax for *every* route, not just MCP ones. Needs measurement against real Vercel cold starts and, if material, either lazy-starting the session manager only when `/api/mcp` is actually hit, or moving MCP to its own deployment/function so it doesn't tax the SPA-serving path.
- **No environment separation.** One Neon database, one Vercel project — no staging vs. production distinction, so there's no safe place to test a risky migration or a new agent prompt against real-shaped data before it's live.
- **No data retention / backup policy** for Neon plan/snapshot tables — `plan_snapshots` grows unboundedly (every mutating turn adds a row, `undo` only pops one) with no pruning job.
- **No structured logging of agent decisions** — for a support/debugging scenario ("why did the agent do X"), there's currently only the SSE event stream in the browser session; nothing is persisted server-side per turn (which tool was called, with what args, whether it errored).

## Risks

| Risk | Likelihood | Impact | Notes |
|---|---|---|---|
| Two people editing the single global plan simultaneously silently clobber each other | High if ever multi-user | Medium | No optimistic concurrency check; last `save_plan` wins |
| Unauthenticated MCP endpoint used to spam/mutate the plan | Medium (only if URL leaks) | Medium | No auth, no rate limit |
| LLM cost runaway from unthrottled `/api/chat` | Medium in production traffic | Medium-High | No per-user/IP rate limit; `MAX_TURNS=6` caps a single turn but not call frequency |
| Postgres undo path breaks in a way unit tests can't catch (only manually verified) | Low-Medium | Medium | First real fix would come from a staging smoke test, not CI |
| Excel round-trip silently drops `lead_days` (custom start dates reset to natural/0) | Medium if Excel becomes the primary editing path | Low-Medium | Documented above (item 10); would need a 6th optional column to fix |

## Prioritized closing order

1. **Wire up CI** (sample workflow below) — cheapest fix, highest leverage; turns every subsequent item into something that can't silently regress.
2. **Auth on `/api/mcp`** — a bearer token check is a small, isolated change and closes the most exploitable gap (unauthenticated write access).
3. **Rate limiting + basic observability on `/api/chat`** — bounds the cost-runaway risk before any real traffic.
4. **Multi-user / multi-plan support (auth + per-plan storage)** — the structural change everything else (concurrency, permissions, audit log) depends on; do this before scaling beyond a single reviewer.
5. ~~Fix `shift_tasks` to real slack-insertion~~ — done (see item 1 above); kept here for history.
6. **Output/input validation beyond prompt guardrails** — add a server-side sanity layer (argument range checks, a diff-based confirmation step for large mutations) once the product has enough real usage to know what "suspicious" looks like.
7. **Automated test coverage for `PostgresStore`** — add once a real Neon staging database is part of the CI/dev loop (item 1 makes this natural to slot in).
8. **Drag-move + mobile touch-drag** — polish items; do last because they're UX completeness, not correctness or safety.

## Sample CI workflow (not yet wired up)

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
  push:
    branches: [master]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt pytest httpx
      - run: ENV=test MOCK_LLM=1 python -m pytest -q

  e2e:
    runs-on: ubuntu-latest
    needs: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: cd frontend && npm install
      - run: cd frontend && npx playwright install --with-deps chromium
      - run: cd frontend && npx playwright test --project=desktop
```
