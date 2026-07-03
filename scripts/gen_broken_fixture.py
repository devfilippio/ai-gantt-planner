"""Generates `frontend/e2e/fixtures/broken.xlsx`: a deliberately invalid
import fixture used by frontend/e2e/excel.spec.ts. Valid headers, but one
task row references a predecessor name that doesn't exist in the file — the
backend's import_plan (api/excel.py) rejects this with a row-level message
("строка N: предшественник '...' не найден"), which the Toolbar surfaces via
a toast.

Run: `.venv/Scripts/python scripts/gen_broken_fixture.py`
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from api.excel import HEADERS

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "frontend" / "e2e" / "fixtures" / "broken.xlsx"
)


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "План"
    ws.append(HEADERS)
    ws.append(["Задача А", "Первая задача", "Мария", 3, ""])
    # References a predecessor name that was never defined above -> row 3
    # (1-indexed with header as row 1) should fail import validation.
    ws.append(["Задача Б", "Зависит от несуществующей задачи", "Иван", 2, "Задача Икс"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
