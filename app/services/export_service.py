"""用例导出为 CSV / Excel,字段对齐常见测试管理工具的导入格式。"""
import csv
import io
from typing import List

from openpyxl import Workbook

from app import models

EXPORT_COLUMNS = ["ID", "标题", "前置条件", "步骤", "预期结果", "用例类型", "优先级", "覆盖点", "审核状态"]

_CASE_TYPE_LABEL = {"functional": "正向功能", "boundary": "边界值/等价类", "exception": "异常/容错"}
_REVIEW_STATUS_LABEL = {"pending": "待审核", "accepted": "已采纳", "rejected": "已驳回", "edited": "已编辑"}


def _flatten_steps(steps: list) -> tuple:
    step_lines = [f"{i + 1}. {s['step']}" for i, s in enumerate(steps)]
    expected_lines = [f"{i + 1}. {s['expected']}" for i, s in enumerate(steps)]
    return "\n".join(step_lines), "\n".join(expected_lines)


def _row_for_case(case: models.TestCase) -> List[str]:
    step_text, expected_text = _flatten_steps(case.steps)
    return [
        str(case.id),
        case.title,
        case.precondition or "",
        step_text,
        expected_text,
        _CASE_TYPE_LABEL.get(case.case_type, case.case_type),
        case.priority,
        "; ".join(case.covers),
        _REVIEW_STATUS_LABEL.get(case.review_status, case.review_status),
    ]


def export_to_csv(cases: List[models.TestCase]) -> io.BytesIO:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for case in cases:
        writer.writerow(_row_for_case(case))
    byte_buf = io.BytesIO(buf.getvalue().encode("utf-8-sig"))  # BOM 方便 Excel 直接识别中文编码
    byte_buf.seek(0)
    return byte_buf


def export_to_xlsx(cases: List[models.TestCase]) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "测试用例"
    ws.append(EXPORT_COLUMNS)
    for case in cases:
        ws.append(_row_for_case(case))
    for i, col in enumerate(EXPORT_COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 24

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
