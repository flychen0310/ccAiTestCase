"""SQLAlchemy ORM 模型,对应 docs/DESIGN.md 的数据模型设计(MVP 阶段暂不包含 knowledge_doc)。"""
import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RequirementStatus(str, enum.Enum):
    draft = "draft"
    analyzing = "analyzing"
    analyzed = "analyzed"
    failed = "failed"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    edited = "edited"


class CaseType(str, enum.Enum):
    functional = "functional"
    boundary = "boundary"
    exception = "exception"


class Priority(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class Requirement(Base):
    __tablename__ = "requirement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    source_ref_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=RequirementStatus.draft.value)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analysis: Mapped[Optional["RequirementAnalysis"]] = relationship(
        back_populates="requirement", uselist=False, cascade="all, delete-orphan"
    )
    cases: Mapped[List["TestCase"]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    batches: Mapped[List["GenerationBatch"]] = relationship(back_populates="requirement", cascade="all, delete-orphan")


class RequirementAnalysis(Base):
    __tablename__ = "requirement_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirement.id"), unique=True)
    feature_points: Mapped[list] = mapped_column(JSON, default=list)
    business_rules: Mapped[list] = mapped_column(JSON, default=list)
    edge_cases: Mapped[list] = mapped_column(JSON, default=list)
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    raw_llm_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    requirement: Mapped["Requirement"] = relationship(back_populates="analysis")


class GenerationBatch(Base):
    __tablename__ = "generation_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirement.id"))
    case_type: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    requirement: Mapped["Requirement"] = relationship(back_populates="batches")
    cases: Mapped[List["TestCase"]] = relationship(back_populates="batch")


class TestCase(Base):
    __tablename__ = "test_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirement.id"))
    gen_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("generation_batch.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    precondition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # [{"step": ..., "expected": ...}, ...]
    case_type: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(16), default=Priority.P1.value)
    covers: Mapped[list] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(32), default=ReviewStatus.pending.value)
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requirement: Mapped["Requirement"] = relationship(back_populates="cases")
    batch: Mapped[Optional["GenerationBatch"]] = relationship(back_populates="cases")
