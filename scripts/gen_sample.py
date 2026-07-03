"""Generates `sample-data/plan.xlsx` from the seed plan.

Used by:
- Excel import E2E specs (frontend/e2e/excel.spec.ts): imports this file to
  assert >=7 bars render.
- The golden-path E2E (frontend/e2e/golden-path.spec.ts): import -> chat
  edit -> export, exercised end to end.

Run: `.venv/Scripts/python scripts/gen_sample.py`
"""
from __future__ import annotations

from pathlib import Path

from api.excel import export_plan, import_plan
from api.seed import seed_plan

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "sample-data" / "plan.xlsx"


def main() -> None:
    plan = seed_plan()
    data = export_plan(plan)

    # Round-trip check: the exported bytes must import back into a valid
    # Plan with the same number of tasks, or the "sample" file would be
    # useless for the excel E2E spec that relies on it.
    roundtripped = import_plan(data)
    assert len(roundtripped.tasks) == len(plan.tasks), (
        f"round-trip mismatch: exported {len(plan.tasks)} tasks, "
        f"re-imported {len(roundtripped.tasks)}"
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(data)
    print(f"Wrote {OUTPUT_PATH} ({len(data)} bytes, {len(plan.tasks)} tasks)")


if __name__ == "__main__":
    main()
