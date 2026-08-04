from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import api_schemas, models
from app.database import get_db
from app.services import export_service

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _get_case_or_404(db: Session, case_id: int) -> models.TestCase:
    case = db.get(models.TestCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    return case


@router.get("/{case_id}", response_model=api_schemas.TestCaseOut)
def get_case(case_id: int, db: Session = Depends(get_db)):
    return _get_case_or_404(db, case_id)


@router.patch("/{case_id}", response_model=api_schemas.TestCaseOut)
def update_case(case_id: int, payload: api_schemas.TestCaseUpdate, db: Session = Depends(get_db)):
    case = _get_case_or_404(db, case_id)
    updates = payload.model_dump(exclude_unset=True)

    if "steps" in updates:
        updates["steps"] = [s if isinstance(s, dict) else s.model_dump() for s in updates["steps"]]

    for field, value in updates.items():
        setattr(case, field, value)

    # 人工手动编辑了内容(而不仅是审核状态)时,自动标记为已编辑,便于统计有多少用例被改动过
    content_fields = {"title", "precondition", "steps", "priority"}
    if content_fields & updates.keys() and "review_status" not in updates:
        case.review_status = models.ReviewStatus.edited.value

    db.commit()
    db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: int, db: Session = Depends(get_db)):
    case = _get_case_or_404(db, case_id)
    db.delete(case)
    db.commit()


@router.post("/export")
def export_cases(payload: api_schemas.ExportRequest, db: Session = Depends(get_db)):
    query = db.query(models.TestCase)
    if payload.requirement_id:
        query = query.filter(models.TestCase.requirement_id == payload.requirement_id)
    if payload.case_ids:
        query = query.filter(models.TestCase.id.in_(payload.case_ids))
    cases = query.order_by(models.TestCase.id).all()

    if not cases:
        raise HTTPException(status_code=404, detail="没有符合条件的用例可导出")

    if payload.format == "csv":
        buf = export_service.export_to_csv(cases)
        media_type, filename = "text/csv", "test_cases.csv"
    else:
        buf = export_service.export_to_xlsx(cases)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "test_cases.xlsx"

    return StreamingResponse(
        buf, media_type=media_type, headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
