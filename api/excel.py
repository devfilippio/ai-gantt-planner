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


def import_plan(data: bytes) -> Plan:
    raise NotImplementedError
