"""FastAPI 请求/响应用的 Pydantic 模型(区别于 app/llm/output_schemas.py 里对 LLM 原始输出的校验模型)。"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------- 需求 ----------


class RequirementCreate(BaseModel):
    title: str
    content: str
    source: str = "manual"
    source_ref_id: Optional[str] = None
    created_by: Optional[str] = None


class FetchLinkRequest(BaseModel):
    url: str


class FetchLinkResponse(BaseModel):
    title: str
    content: str
    source: str
    source_ref_id: Optional[str] = None


class RequirementImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    url: str = ""

    @model_validator(mode="after")
    def _fill_url(self):
        if not self.url:
            self.url = f"/api/requirements/images/{self.id}/raw"
        return self


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    source: str
    source_ref_id: Optional[str]
    status: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime


class RequirementAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    feature_points: List[str]
    business_rules: List[str]
    edge_cases: List[str]
    open_questions: List[str]
    created_at: datetime


class RequirementAnalysisUpdate(BaseModel):
    """人工修正 AI 需求理解结果(AI 理解有偏差时人为介入)。只传要改的字段。"""

    feature_points: Optional[List[str]] = None
    business_rules: Optional[List[str]] = None
    edge_cases: Optional[List[str]] = None
    open_questions: Optional[List[str]] = None


class RequirementDetailOut(RequirementOut):
    analysis: Optional[RequirementAnalysisOut] = None
    images: List[RequirementImageOut] = Field(default_factory=list)


# ---------- 用例生成 ----------


class GenerateRequest(BaseModel):
    case_types: List[str] = Field(default_factory=lambda: ["functional", "boundary", "exception"])


class GenerationStageResult(BaseModel):
    case_type: str
    generated_count: int
    status: str
    error_message: Optional[str] = None
    input_tokens: int
    output_tokens: int
    latency_ms: float


class GenerateResponse(BaseModel):
    requirement_id: int
    stages: List[GenerationStageResult]
    total_cases: int


# ---------- 用例 ----------


class CaseStepOut(BaseModel):
    step: str
    expected: str


class TestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    gen_batch_id: Optional[int]
    title: str
    precondition: Optional[str]
    steps: List[CaseStepOut]
    case_type: str
    priority: str
    covers: List[str]
    review_status: str
    review_comment: Optional[str]
    source: str = ""  # 派生字段:ai=AI 生成,manual=人工新增(按是否关联生成批次推断)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _fill_source(self):
        if not self.source:
            self.source = "ai" if self.gen_batch_id is not None else "manual"
        return self


class TestCaseCreate(BaseModel):
    """人工手动补充用例(AI 没覆盖到的场景)。不关联生成批次,来源标记为 manual。"""

    title: str
    precondition: Optional[str] = None
    steps: List[CaseStepOut] = Field(default_factory=list)
    case_type: str = "functional"
    priority: str = "P1"
    covers: List[str] = Field(default_factory=list)
    review_status: str = "accepted"  # 人工亲自补的默认视为已采纳,可在编辑弹窗调整


class TestCaseUpdate(BaseModel):
    title: Optional[str] = None
    precondition: Optional[str] = None
    steps: Optional[List[CaseStepOut]] = None
    case_type: Optional[str] = None
    priority: Optional[str] = None
    review_status: Optional[str] = None
    review_comment: Optional[str] = None


class ExportRequest(BaseModel):
    requirement_id: Optional[int] = None
    case_ids: Optional[List[int]] = None
    format: str = "xlsx"


# ---------- 用例统计 ----------


class RequirementStatsOut(BaseModel):
    """单个需求下的用例统计:来源分布(召回率)+ 审核分布(采纳率)。"""

    requirement_id: int
    total: int  # 用例总数
    ai_count: int  # AI 生成的用例数
    manual_count: int  # 人工新增补充的用例数
    pending: int
    accepted: int
    rejected: int
    edited: int
    reviewed: int  # 已审核数 = accepted + rejected + edited(采纳率的分母)
    # 召回率 = AI 生成数 ÷ 最终用例总数(含人工补充);人工补得越多说明 AI 漏得越多、召回率越低
    recall_rate: Optional[float] = None
    # 采纳率 = accepted ÷ 已审核数(排除还没审核的 pending)
    acceptance_rate: Optional[float] = None


# ---------- RAG 知识库 ----------


class KnowledgeDocCreate(BaseModel):
    doc_type: str = "test_spec"
    content: str
    metadata: dict = Field(default_factory=dict)


class KnowledgeDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_type: str
    content: str
    metadata: dict = Field(validation_alias="metadata_")
    created_at: datetime


class ImportAcceptedCasesRequest(BaseModel):
    requirement_id: Optional[int] = None


class ImportAcceptedCasesResponse(BaseModel):
    imported: int
    skipped_existing: int
    total_accepted: int
