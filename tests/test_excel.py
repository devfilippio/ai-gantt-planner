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
