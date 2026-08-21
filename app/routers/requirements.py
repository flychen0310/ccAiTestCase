from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import api_schemas, models
from app.database import get_db
from app.services import image_service, pipeline_service
from app.services.doc_fetcher import DocFetchError, fetch_from_url
from app.services.image_service import ImageUploadError

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


@router.post("/fetch-link", response_model=api_schemas.FetchLinkResponse)
def fetch_link(payload: api_schemas.FetchLinkRequest):
    """抓取外部文档链接(当前支持飞书文档)的标题和纯文本,不落库。

    前端拿到后填充到新建需求表单,用户确认/微调后再正式创建需求。
    """
    try:
        doc = fetch_from_url(payload.url)
    except DocFetchError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return api_schemas.FetchLinkResponse(
        title=doc.title, content=doc.content, source=doc.source, source_ref_id=doc.source_ref_id
    )


def _get_image_or_404(db: Session, image_id: int) -> models.RequirementImage:
    image = db.get(models.RequirementImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")
    return image


@router.post("/{requirement_id}/images", response_model=List[api_schemas.RequirementImageOut])
async def upload_images(
    requirement_id: int, files: List[UploadFile] = File(...), db: Session = Depends(get_db)
):
    """给需求上传配图(界面原型/流程图/接口截图等),供 AI 需求理解时结合分析。"""
    requirement = _get_requirement_or_404(db, requirement_id)
    uploads = [(f.filename or "image", f.content_type or "", await f.read()) for f in files]
    try:
        saved = image_service.save_uploads(db, requirement, uploads)
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return saved


@router.get("/{requirement_id}/images", response_model=List[api_schemas.RequirementImageOut])
def list_images(requirement_id: int, db: Session = Depends(get_db)):
    requirement = _get_requirement_or_404(db, requirement_id)
    return requirement.images


@router.get("/images/{image_id}/raw")
def get_image_raw(image_id: int, db: Session = Depends(get_db)):
    image = _get_image_or_404(db, image_id)
    path = image_service.abs_path(image)
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片文件已丢失")
    return FileResponse(path, media_type=image.content_type, filename=image.filename)


@router.delete("/images/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    image = _get_image_or_404(db, image_id)
    image_service.delete_image(db, image)
    return {"deleted": image_id}


@router.get("", response_model=List[api_schemas.RequirementOut])
def list_requirements(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Requirement)
    if status:
        query = query.filter(models.Requirement.status == status)
    return query.order_by(models.Requirement.id.desc()).all()


@router.get("/{requirement_id}", response_model=api_schemas.RequirementDetailOut)
def get_requirement(requirement_id: int, db: Session = Depends(get_db)):
    return _get_requirement_or_404(db, requirement_id)


@router.delete("/{requirement_id}")
def delete_requirement(requirement_id: int, db: Session = Depends(get_db)):
    """删除需求,连同其配图、需求理解、用例、生成批次一并清理。

    数据库子记录由 SQLAlchemy 级联删除;配图的磁盘文件需在这里先行清理,避免残留。
    """
    requirement = _get_requirement_or_404(db, requirement_id)
    for image in requirement.images:
        path = image_service.abs_path(image)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # 文件删不掉不阻塞需求删除
    db.delete(requirement)
    db.commit()
    return {"deleted": requirement_id}


@router.post("/{requirement_id}/analyze", response_model=api_schemas.RequirementAnalysisOut)
def analyze_requirement(requirement_id: int, db: Session = Depends(get_db)):
    requirement = _get_requirement_or_404(db, requirement_id)
    try:
        return pipeline_service.analyze_requirement(db, requirement)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.patch("/{requirement_id}/analysis", response_model=api_schemas.RequirementAnalysisOut)
def update_analysis(
    requirement_id: int, payload: api_schemas.RequirementAnalysisUpdate, db: Session = Depends(get_db)
):
    """人工修正 AI 需求理解结果(AI 理解有偏差时人为介入)。"""
    requirement = _get_requirement_or_404(db, requirement_id)
    analysis = requirement.analysis
    if not analysis:
        raise HTTPException(status_code=404, detail="该需求还没有需求理解结果,请先执行 AI 需求理解")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的内容")
    for field, value in updates.items():
        setattr(analysis, field, value)
    db.commit()
    db.refresh(analysis)
    return analysis


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


@router.post("/{requirement_id}/cases", response_model=api_schemas.TestCaseOut)
def create_case_manually(
    requirement_id: int, payload: api_schemas.TestCaseCreate, db: Session = Depends(get_db)
):
    """人工手动补充用例(AI 没覆盖到的场景)。不关联生成批次,来源自动记为 manual。"""
    _get_requirement_or_404(db, requirement_id)
    valid_types = {t.value for t in models.CaseType}
    if payload.case_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"用例类型非法,可选值: {sorted(valid_types)}")

    case = models.TestCase(
        requirement_id=requirement_id,
        gen_batch_id=None,  # 人工新增,不关联 AI 生成批次 -> 据此判定来源为 manual
        title=payload.title,
        precondition=payload.precondition,
        steps=[s.model_dump() for s in payload.steps],
        case_type=payload.case_type,
        priority=payload.priority,
        covers=payload.covers,
        review_status=payload.review_status,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.get("/{requirement_id}/stats", response_model=api_schemas.RequirementStatsOut)
def get_requirement_stats(requirement_id: int, db: Session = Depends(get_db)):
    """用例统计:来源分布(召回率)+ 审核分布(采纳率)。"""
    _get_requirement_or_404(db, requirement_id)
    cases = db.query(models.TestCase).filter(models.TestCase.requirement_id == requirement_id).all()

    total = len(cases)
    ai_count = sum(1 for c in cases if c.gen_batch_id is not None)
    manual_count = total - ai_count

    pending = sum(1 for c in cases if c.review_status == models.ReviewStatus.pending.value)
    accepted = sum(1 for c in cases if c.review_status == models.ReviewStatus.accepted.value)
    rejected = sum(1 for c in cases if c.review_status == models.ReviewStatus.rejected.value)
    edited = sum(1 for c in cases if c.review_status == models.ReviewStatus.edited.value)
    reviewed = accepted + rejected + edited

    # 采纳率 = 已采纳 ÷ 已审核(排除还没审核的 pending)
    acceptance_rate = round(accepted / reviewed, 4) if reviewed else None

    # 召回率(AI 覆盖率)= AI 保留下来的用例 ÷ 最终用例总数(均排除被驳回的用例)。
    # 人工补充越多、被保留的 AI 用例越少,召回率越低。
    final_total = total - rejected
    ai_kept = sum(
        1 for c in cases
        if c.gen_batch_id is not None and c.review_status != models.ReviewStatus.rejected.value
    )
    recall_rate = round(ai_kept / final_total, 4) if final_total else None

    return api_schemas.RequirementStatsOut(
        requirement_id=requirement_id,
        total=total,
        ai_count=ai_count,
        manual_count=manual_count,
        pending=pending,
        accepted=accepted,
        rejected=rejected,
        edited=edited,
        reviewed=reviewed,
        recall_rate=recall_rate,
        acceptance_rate=acceptance_rate,
    )
