"""FastAPI 请求/响应用的 Pydantic 模型(区别于 app/llm/output_schemas.py 里对 LLM 原始输出的校验模型)。"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------- 需求 ----------


class RequirementCreate(BaseModel):
    title: str
    content: str
    source: str = "manual"
    source_ref_id: Optional[str] = None
    created_by: Optional[str] = None


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


class RequirementDetailOut(RequirementOut):
    analysis: Optional[RequirementAnalysisOut] = None


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
    created_at: datetime
    updated_at: datetime


class TestCaseUpdate(BaseModel):
    title: Optional[str] = None
    precondition: Optional[str] = None
    steps: Optional[List[CaseStepOut]] = None
    priority: Optional[str] = None
    review_status: Optional[str] = None
    review_comment: Optional[str] = None


class ExportRequest(BaseModel):
    requirement_id: Optional[int] = None
    case_ids: Optional[List[int]] = None
    format: str = "xlsx"


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
