"""Model bake-off: scores a candidate LLM against the three REAL prod
failures (F1 fabrication, F2 plan-dump/markdown parroting, F3 update/delete
churn) plus two sanity scenarios, using the REAL OpenRouter API end-to-end.

Why: after switching the agent's primary model to openai/gpt-4o-mini, the
owner hit three failures on prod. Part 1 fixed the harness (no more full-plan
echo after mutations, anti-fabrication + no-markdown + single-update-call
rules in the system prompt, a `no_tools` debug event). This script answers
the OTHER half of the question: with the harness fixed, is gpt-4o-mini (or
some other cheap model) actually reliable enough, or do we need a stronger
model as PRIMARY?

Each candidate is tested as BOTH PRIMARY and FALLBACK (OpenRouterLLM with
PRIMARY_MODEL = FALLBACK_MODEL = candidate) so a failure can't silently
escalate to a stronger fallback model and hide a real problem.

Scenarios (fresh seed_plan() each time, real run_agent_turn loop):
  S1 "перенеси задачи Олега на неделю" x3 reps — PASS iff EVERY rep calls
     shift_tasks(assignee=Олег, days=7) EXACTLY ONCE (and no other mutating
     call) and the final message is short (<=220 chars), has no '**', and
     doesn't contain 3+ '·' (a compact_plan dump marker). A duplicate correct
     call is NOT a pass — it silently double-shifts the plan (lead_days
     accumulates), and an extra call for an unrequested assignee is a real
     over-mutation bug, not just verbosity.
  S2 "добавь Ольге задачу купить молоко" (no dates) — add_task called with
     assignee Ольга; reply short.
  S3 (continues S2's history) "пусть она купит молоко с 4 по 10 июля" — PASS
     iff EXACTLY ONE mutating call and it is update_task with
     start_date=2026-07-04 (duration 6 or 7 both accepted); FAIL if
     delete_task or add_task appear anywhere in the turn.
  S4 "сделай план красивее" — zero tool calls, a clarifying question.
  S5 "добавь задачу Настройка аналитики, Иван, 3 дня, после вёрстки" —
     add_task called with a predecessor that resolves to the frontend task;
     reply short.

PRIORITY UPDATE (quality over cost — sonnet-grade or bust): a candidate only
qualifies as PRIMARY if it passes S1-S5 (5/5, with S1 requiring all 3 reps to
be exactly-one-correct-call — ANY fabrication, wrong args, extra/duplicate
mutating call, or plan-dump reply disqualifies it) AND additionally passes
8/8 on the first 8 scenarios of scripts/chaos_chat.py's BATTERY (vague
request, off-domain question, destructive bulk delete, partial-name delete,
nonexistent assignee, bulk shift ALL assignees, swap assignees, English
command). If no cheaper candidate clears this bar, PRIMARY_MODEL reverts to
anthropic/claude-sonnet-4.5 (FALLBACK openai/gpt-4o) — a fully acceptable
outcome; quality is not traded for cost.

Usage (requires OPENROUTER_API_KEY loaded):
    set -a && . ./.env && set +a
    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/model_bakeoff.py \\
        openai/gpt-4o-mini google/gemini-2.5-flash anthropic/claude-haiku-4.5 openai/gpt-4o

Stops at the first model that scores 5/5 on S1-S5 AND 8/8 on the chaos-8.
Prints a per-model, per-scenario pass/fail table plus an approximate
OpenRouter cost delta (from the auth/key endpoint's cumulative `usage`
field, sampled before/after each model's scenarios), a SONNET-GRADE / NOT
verdict line per candidate, and a final recommendation.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from api.agent import OpenRouterLLM, run_agent_turn
from api.seed import seed_plan

DEFAULT_CANDIDATES = [
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-4o",
]

MAX_MSG_LEN = 220


def _key_usage(api_key: str) -> float | None:
    """Cumulative OpenRouter spend on this key, in USD, from the auth/key
    endpoint. Returns None if the lookup fails (network hiccup, bad key) —
    cost reporting is best-effort and must never crash the bake-off."""
    try:
        r = httpx.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        r.raise_for_status()
        return float(r.json()["data"]["usage"])
    except Exception:
        return None


def _candidate_llm(model_id: str) -> OpenRouterLLM:
    """An OpenRouterLLM pinned to a single model for BOTH primary and
    fallback slots, so a scenario can't quietly escalate to a stronger model
    and mask how the candidate actually performs."""
    llm = OpenRouterLLM()
    llm.PRIMARY_MODEL = model_id
    llm.FALLBACK_MODEL = model_id
    return llm


@dataclass
class TurnResult:
    tool_calls: list[dict] = field(default_factory=list)
    final_message: str = ""
    events: list[dict] = field(default_factory=list)


def _run_turn(message: str, plan, llm, history: list[dict] | None = None) -> TurnResult:
    tr = TurnResult()
    for event in run_agent_turn(message, plan, llm=llm, history=history):
        tr.events.append(event)
        if event["type"] == "tool_call":
            tr.tool_calls.append({"tool": event["tool"], "args": event["args"]})
        elif event["type"] == "message":
            tr.final_message = event["text"]
    return tr


def _looks_like_plan_dump(text: str) -> bool:
    return text.count("·") >= 3


def _no_markdown(text: str) -> bool:
    return "**" not in text


def _short(text: str) -> bool:
    return len(text) <= MAX_MSG_LEN


_CLARIFY_MARKERS = ("?", "уточн", "какие именно", "какую именно", "какой именно")


def _is_clarifying_reply(text: str) -> bool:
    """A tool-free reply counts as "asked a clarifying question" if it either
    ends in a literal '?' or uses one of the standard Russian clarify verbs
    ('уточните') — some models phrase a genuine clarifying request as a
    polite imperative without a question mark ('Пожалуйста, уточните...')."""
    low = text.lower()
    return any(m in low for m in _CLARIFY_MARKERS)


@dataclass
class ScenarioOutcome:
    name: str
    passed: bool
    detail: str


def scenario_s1(model_id: str) -> ScenarioOutcome:
    """PASS iff the turn calls shift_tasks(assignee=Олег, days=7) EXACTLY
    ONCE, and no other mutating call happens. This is stricter than "at
    least one correct call": a real bake-off run against gpt-4o-mini turned
    up BOTH (a) a duplicate shift_tasks(Олег, 7) call in the same turn - which
    silently double-shifts the plan (14 days of lead instead of 7, since
    shift_tasks adds to existing lead_days) - and (b) an unrequested
    shift_tasks(Анна, 7) call the user never asked for. Both are real
    correctness bugs that an "at least one correct call" check would have
    scored as a pass."""
    reps_ok = []
    details = []
    for rep in range(3):
        plan = seed_plan()
        llm = _candidate_llm(model_id)
        tr = _run_turn("перенеси задачи Олега на неделю", plan, llm)
        mutating = [tc for tc in tr.tool_calls if tc["tool"] != "get_plan"]
        correct_shift = [
            tc for tc in mutating
            if tc["tool"] == "shift_tasks"
            and tc["args"].get("assignee") == "Олег"
            and tc["args"].get("days") == 7
        ]
        exactly_one_correct_call = len(mutating) == 1 and len(correct_shift) == 1
        ok = (
            exactly_one_correct_call
            and _short(tr.final_message)
            and _no_markdown(tr.final_message)
            and not _looks_like_plan_dump(tr.final_message)
        )
        reps_ok.append(ok)
        details.append(
            f"rep{rep+1}: tools={[(c['tool'], c['args']) for c in tr.tool_calls]} "
            f"exactly_one_correct={exactly_one_correct_call} len={len(tr.final_message)} "
            f"md={'**' in tr.final_message} dump={_looks_like_plan_dump(tr.final_message)} "
            f"msg={tr.final_message[:120]!r}"
        )
    return ScenarioOutcome("S1 shift Олег x3", all(reps_ok), " | ".join(details))


def scenario_s2_s3(model_id: str) -> tuple[ScenarioOutcome, ScenarioOutcome, list[dict]]:
    plan = seed_plan()
    llm = _candidate_llm(model_id)
    tr2 = _run_turn("добавь Ольге задачу купить молоко", plan, llm)
    add_calls = [tc for tc in tr2.tool_calls if tc["tool"] == "add_task"]
    s2_ok = bool(add_calls) and _short(tr2.final_message)
    s2 = ScenarioOutcome(
        "S2 add milk (Ольга)", s2_ok,
        f"tools={[c['tool'] for c in tr2.tool_calls]} len={len(tr2.final_message)} "
        f"msg={tr2.final_message[:120]!r}",
    )

    history = [
        {"role": "user", "text": "добавь Ольге задачу купить молоко"},
        {"role": "agent", "text": tr2.final_message},
    ]
    # S3 must see the plan AFTER S2's mutation (the milk task now exists) —
    # apply the last patch event from S2 onto the plan we hand to S3, exactly
    # like /api/chat would (the store persists mutations between turns).
    patch_events = [e for e in tr2.events if e["type"] == "patch"]
    plan_after_s2 = plan
    if patch_events:
        from api.models import Plan
        plan_after_s2 = Plan(**patch_events[-1]["plan_patch"]["plan"])

    tr3 = _run_turn("пусть она купит молоко с 4 по 10 июля", plan_after_s2, llm, history=history)
    mutating = [tc for tc in tr3.tool_calls if tc["tool"] != "get_plan"]
    update_calls = [tc for tc in mutating if tc["tool"] == "update_task"]
    bad_calls = [tc for tc in mutating if tc["tool"] in ("delete_task", "add_task")]
    date_ok = any(
        tc["args"].get("start_date") == "2026-07-04"
        and tc["args"].get("duration_days") in (None, 6, 7)
        for tc in update_calls
    )
    s3_ok = len(mutating) == 1 and bool(update_calls) and not bad_calls and date_ok
    s3 = ScenarioOutcome(
        "S3 reschedule milk (no churn)", s3_ok,
        f"tools={[(c['tool'], c['args']) for c in tr3.tool_calls]} "
        f"mutating_count={len(mutating)} date_ok={date_ok} "
        f"msg={tr3.final_message[:120]!r}",
    )
    return s2, s3, tr3.tool_calls


def scenario_s4(model_id: str) -> ScenarioOutcome:
    plan = seed_plan()
    llm = _candidate_llm(model_id)
    tr = _run_turn("сделай план красивее", plan, llm)
    ok = not tr.tool_calls and bool(tr.final_message.strip())
    return ScenarioOutcome(
        "S4 vague request -> clarify", ok,
        f"tools={[c['tool'] for c in tr.tool_calls]} msg={tr.final_message[:160]!r}",
    )


def scenario_s5(model_id: str) -> ScenarioOutcome:
    plan = seed_plan()
    llm = _candidate_llm(model_id)
    tr = _run_turn(
        "добавь задачу Настройка аналитики, Иван, 3 дня, после вёрстки", plan, llm,
    )
    add_calls = [tc for tc in tr.tool_calls if tc["tool"] == "add_task"]
    pred_ok = False
    for tc in add_calls:
        preds = tc["args"].get("predecessors") or []
        # Accept either the resolved id or the name the model saw in
        # compact_plan - tool_registry resolves names to ids downstream, so
        # both count as "correctly pointed at the frontend task".
        if any(p == "frontend" or "вёрстк" in str(p).lower() for p in preds):
            pred_ok = True
    ok = bool(add_calls) and pred_ok and _short(tr.final_message)
    return ScenarioOutcome(
        "S5 add analytics task", ok,
        f"tools={[(c['tool'], c['args']) for c in tr.tool_calls]} "
        f"msg={tr.final_message[:120]!r}",
    )


# --- Chaos-8: the first 8 scenarios of scripts/chaos_chat.py's BATTERY,
# auto-scored. chaos_chat.py itself only *reports* what happened (it's a
# human-reviewed harness); these pass/fail rules encode what "sensible
# behavior" means for each of the 8 so the bake-off can gate on them too.

def _chaos_turn(model_id: str, message: str) -> TurnResult:
    plan = seed_plan()
    llm = _candidate_llm(model_id)
    return _run_turn(message, plan, llm)


def chaos_1_vague(model_id: str) -> ScenarioOutcome:
    tr = _chaos_turn(model_id, "сделай план красивее")
    ok = not tr.tool_calls and bool(tr.final_message.strip())
    return ScenarioOutcome("C1 vague/no-op", ok, f"tools={len(tr.tool_calls)} msg={tr.final_message[:120]!r}")


def chaos_2_offdomain(model_id: str) -> ScenarioOutcome:
    tr = _chaos_turn(model_id, "какая погода в Москве?")
    ok = not tr.tool_calls and bool(tr.final_message.strip())
    return ScenarioOutcome("C2 off-domain (weather)", ok, f"tools={len(tr.tool_calls)} msg={tr.final_message[:120]!r}")


def chaos_3_bulk_delete(model_id: str) -> ScenarioOutcome:
    """'удали все задачи' is unambiguous and destructive but explicit — a
    sensible agent complies (delete_task per task) or clarifies once; it must
    NOT fabricate a deletion without calling delete_task, and must not leave
    tasks referencing deleted ids."""
    tr = _chaos_turn(model_id, "удали все задачи")
    delete_calls = [tc for tc in tr.tool_calls if tc["tool"] == "delete_task"]
    clarified = not tr.tool_calls and _is_clarifying_reply(tr.final_message)
    ok = bool(delete_calls) or clarified
    return ScenarioOutcome(
        "C3 destructive bulk delete", ok,
        f"deletes={len(delete_calls)} clarified={clarified} msg={tr.final_message[:120]!r}",
    )


def chaos_4_partial_name_delete(model_id: str) -> ScenarioOutcome:
    """'удали задачу дизайн' names exactly one task ('Дизайн лендинга') by a
    substring — a correct agent resolves it and deletes that one task, or
    asks which one if genuinely unsure. It must never delete an unrelated
    task."""
    tr = _chaos_turn(model_id, "удали задачу дизайн")
    delete_calls = [tc for tc in tr.tool_calls if tc["tool"] == "delete_task"]
    wrong_delete = [tc for tc in delete_calls if tc["args"].get("id") not in ("design", "Дизайн лендинга")]
    clarified = not tr.tool_calls and _is_clarifying_reply(tr.final_message)
    ok = (bool(delete_calls) and not wrong_delete) or clarified
    return ScenarioOutcome(
        "C4 partial-name delete", ok,
        f"deletes={[tc['args'] for tc in delete_calls]} clarified={clarified} msg={tr.final_message[:120]!r}",
    )


def chaos_5_nonexistent_assignee(model_id: str) -> ScenarioOutcome:
    """'перенеси задачи Пети на неделю' — Петя doesn't exist in the seed plan
    (Мария/Иван/Олег/Анна). A correct agent must NOT silently shift the whole
    plan or fabricate a change — it should either call shift_tasks(Петя, ...)
    (a no-op since no task matches, which the tool layer handles harmlessly)
    or explain nobody named Петя has tasks. It must NOT shift any real
    assignee's tasks (that would be acting on the wrong person)."""
    tr = _chaos_turn(model_id, "перенеси задачи Пети на неделю")
    mutating = [tc for tc in tr.tool_calls if tc["tool"] != "get_plan"]
    wrong_target = [
        tc for tc in mutating
        if tc["tool"] == "shift_tasks" and tc["args"].get("assignee") not in (None, "Петя", "Пети")
    ]
    explained = not tr.tool_calls and bool(tr.final_message.strip())
    ok = (not wrong_target) and (bool(mutating) or explained)
    return ScenarioOutcome(
        "C5 nonexistent assignee (Петя)", ok,
        f"tools={[(c['tool'], c['args']) for c in tr.tool_calls]} msg={tr.final_message[:120]!r}",
    )


def chaos_6_bulk_shift_all(model_id: str) -> ScenarioOutcome:
    """'увеличь все задачи на 2 дня' means duration +2 for every task, NOT a
    schedule shift — shift_tasks would be the wrong tool (it moves start
    dates, doesn't change duration). A correct agent calls update_task per
    task with duration_days = old+2 (or a bulk equivalent), not shift_tasks."""
    plan = seed_plan()
    llm = _candidate_llm(model_id)
    tr = _run_turn("увеличь все задачи на 2 дня", plan, llm)
    update_calls = [tc for tc in tr.tool_calls if tc["tool"] == "update_task" and "duration_days" in tc["args"]]
    shift_calls = [tc for tc in tr.tool_calls if tc["tool"] == "shift_tasks"]
    by_id = {t.id: t for t in plan.tasks}
    correct_updates = [
        tc for tc in update_calls
        if tc["args"].get("id") in by_id
        and tc["args"]["duration_days"] == by_id[tc["args"]["id"]].duration_days + 2
    ]
    ok = len(correct_updates) == len(plan.tasks) and not shift_calls
    return ScenarioOutcome(
        "C6 bulk +2 days duration (all)", ok,
        f"correct_updates={len(correct_updates)}/{len(plan.tasks)} shift_calls={len(shift_calls)} "
        f"msg={tr.final_message[:120]!r}",
    )


def chaos_7_swap_assignees(model_id: str) -> ScenarioOutcome:
    """'поменяй местами исполнителей у QA и дизайна' — QA(Олег) <-> design(Анна).
    A correct agent ends with qa.assignee == Анна and design.assignee ==
    Олег. This needs two update_task calls (a plain reassign_tasks by name
    would wrongly move ALL of Олег's/Анна's tasks, not just these two)."""
    plan = seed_plan()
    llm = _candidate_llm(model_id)
    tr = _run_turn("поменяй местами исполнителей у QA и дизайна", plan, llm)
    # Apply the actual patch stream to see the resulting plan state (rather
    # than inspecting individual tool_call args, which vary by strategy —
    # some models use two update_task calls, others a temp reassign dance).
    from api.models import Plan
    final_plan = plan
    for e in tr.events:
        if e["type"] == "patch":
            final_plan = Plan(**e["plan_patch"]["plan"])
    by_id = {t.id: t for t in final_plan.tasks}
    qa_ok = by_id.get("qa") is not None and by_id["qa"].assignee == "Анна"
    design_ok = by_id.get("design") is not None and by_id["design"].assignee == "Олег"
    others_untouched = all(
        by_id[t.id].assignee == t.assignee for t in plan.tasks if t.id not in ("qa", "design")
    )
    ok = qa_ok and design_ok and others_untouched
    return ScenarioOutcome(
        "C7 swap assignees (QA<->design)", ok,
        f"qa->{by_id.get('qa').assignee if by_id.get('qa') else '?'} "
        f"design->{by_id.get('design').assignee if by_id.get('design') else '?'} "
        f"others_untouched={others_untouched} msg={tr.final_message[:120]!r}",
    )


def chaos_8_english(model_id: str) -> ScenarioOutcome:
    """'make QA 10 days long' — English input naming the QA task by its
    domain meaning. A correct agent calls update_task(id=qa,
    duration_days=10)."""
    tr = _chaos_turn(model_id, "make QA 10 days long")
    update_calls = [
        tc for tc in tr.tool_calls
        if tc["tool"] == "update_task"
        and tc["args"].get("id") in ("qa", "QA и тестирование")
        and tc["args"].get("duration_days") == 10
    ]
    ok = bool(update_calls)
    return ScenarioOutcome(
        "C8 English command (QA=10d)", ok,
        f"tools={[(c['tool'], c['args']) for c in tr.tool_calls]} msg={tr.final_message[:120]!r}",
    )


CHAOS_8_FUNCS = [
    chaos_1_vague, chaos_2_offdomain, chaos_3_bulk_delete, chaos_4_partial_name_delete,
    chaos_5_nonexistent_assignee, chaos_6_bulk_shift_all, chaos_7_swap_assignees, chaos_8_english,
]


def run_bakeoff(model_id: str, api_key: str) -> dict:
    usage_before = _key_usage(api_key)

    s1 = scenario_s1(model_id)
    s2, s3, _ = scenario_s2_s3(model_id)
    s4 = scenario_s4(model_id)
    s5 = scenario_s5(model_id)
    s_outcomes = [s1, s2, s3, s4, s5]

    chaos_outcomes = [f(model_id) for f in CHAOS_8_FUNCS]

    usage_after = _key_usage(api_key)
    cost_delta = None
    if usage_before is not None and usage_after is not None:
        cost_delta = round(usage_after - usage_before, 5)

    s_score = sum(1 for o in s_outcomes if o.passed)
    chaos_score = sum(1 for o in chaos_outcomes if o.passed)
    sonnet_grade = (s_score == 5) and (chaos_score == 8)
    return {
        "model": model_id,
        "s_outcomes": s_outcomes,
        "chaos_outcomes": chaos_outcomes,
        "s_score": s_score,
        "chaos_score": chaos_score,
        "sonnet_grade": sonnet_grade,
        "cost_delta_usd": cost_delta,
    }


def _print_report(result: dict) -> None:
    cost = result["cost_delta_usd"] if result["cost_delta_usd"] is not None else "unknown"
    print(f"\n{'='*70}")
    print(f"MODEL: {result['model']}")
    print(f"  S1-S5:    {result['s_score']}/5")
    print(f"  chaos-8:  {result['chaos_score']}/8")
    print(f"  cost~${cost}")
    verdict = "SONNET-GRADE" if result["sonnet_grade"] else "NOT SONNET-GRADE"
    print(f"  вердикт по качеству: {verdict}")
    print("=" * 70)
    print("  -- S1-S5 --")
    for o in result["s_outcomes"]:
        status = "PASS" if o.passed else "FAIL"
        print(f"  [{status}] {o.name}")
        print(f"         {o.detail}")
    print("  -- chaos-8 --")
    for o in result["chaos_outcomes"]:
        status = "PASS" if o.passed else "FAIL"
        print(f"  [{status}] {o.name}")
        print(f"         {o.detail}")


def main() -> None:
    import os

    api_key = os.environ["OPENROUTER_API_KEY"]
    candidates = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_CANDIDATES

    results = []
    winner = None
    for model_id in candidates:
        print(f"\n>>> Testing {model_id} ...")
        result = run_bakeoff(model_id, api_key)
        results.append(result)
        _print_report(result)
        if result["sonnet_grade"]:
            winner = model_id
            print(f"\n*** {model_id} is SONNET-GRADE (5/5 + 8/8) - stopping bake-off here. ***")
            break

    print(f"\n\n{'#'*70}")
    print("SUMMARY")
    print("#" * 70)
    header = f"{'model':30s} {'S1-S5':>6s} {'chaos8':>7s} {'verdict':>16s} {'cost($)':>10s}"
    print(header)
    for r in results:
        verdict = "SONNET-GRADE" if r["sonnet_grade"] else "not sonnet-grade"
        cost = r["cost_delta_usd"] if r["cost_delta_usd"] is not None else "?"
        print(f"{r['model']:30s} {r['s_score']}/5{'':>3s} {r['chaos_score']}/8{'':>3s} {verdict:>16s} {cost!s:>10s}")

    if winner:
        print(f"\nWINNER (first SONNET-GRADE candidate, priority order): {winner}")
    else:
        print("\nNo candidate reached SONNET-GRADE (5/5 on S1-S5 AND 8/8 on chaos-8).")
        print("Per instructions: fall back to PRIMARY_MODEL = anthropic/claude-sonnet-4.5, "
              "FALLBACK_MODEL = openai/gpt-4o. Quality is not traded for cost.")


if __name__ == "__main__":
    main()
