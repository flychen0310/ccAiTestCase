from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import api_schemas, models
from app.database import get_db
from app.services import pipeline_service

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


def _get_requirement_or_404(db: Session, requirement_id: int) -> models.Requirement:
    requirement = db.get(models.Requirement, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="需求不存在")
    return requirement


@router.post("", response_model=api_schemas.RequirementOut)
def create_requirement(payload: api_schemas.RequirementCreate, db: Session = Depends(get_db)):
    requirement = models.Requirement(**payload.model_dump())
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement


@router.get("", response_model=List[api_schemas.RequirementOut])
def list_requirements(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Requirement)
    if status:
        query = query.filter(models.Requirement.status == status)
    return query.order_by(models.Requirement.id.desc()).all()


@router.get("/{requirement_id}", response_model=api_schemas.RequirementDetailOut)
def get_requirement(requirement_id: int, db: Session = Depends(get_db)):
    return _get_requirement_or_404(db, requirement_id)


@router.post("/{requirement_id}/analyze", response_model=api_schemas.RequirementAnalysisOut)
def analyze_requirement(requirement_id: int, db: Session = Depends(get_db)):
    requirement = _get_requirement_or_404(db, requirement_id)
    try:
        return pipeline_service.analyze_requirement(db, requirement)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/{requirement_id}/generate", response_model=api_schemas.GenerateResponse)
def generate_cases(
    requirement_id: int, payload: api_schemas.GenerateRequest, db: Session = Depends(get_db)
):
    requirement = _get_requirement_or_404(db, requirement_id)
    try:
        stage_results = pipeline_service.generate_cases(db, requirement, payload.case_types)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return api_schemas.GenerateResponse(
        requirement_id=requirement_id,
        stages=[api_schemas.GenerationStageResult(**r) for r in stage_results],
        total_cases=sum(r["generated_count"] for r in stage_results),
    )


@router.get("/{requirement_id}/cases", response_model=List[api_schemas.TestCaseOut])
def list_cases_for_requirement(
    requirement_id: int,
    case_type: Optional[str] = None,
    review_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _get_requirement_or_404(db, requirement_id)
    query = db.query(models.TestCase).filter(models.TestCase.requirement_id == requirement_id)
    if case_type:
        query = query.filter(models.TestCase.case_type == case_type)
    if review_status:
        query = query.filter(models.TestCase.review_status == review_status)
    return query.order_by(models.TestCase.id).all()
