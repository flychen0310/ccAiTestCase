"""LLM 输出的结构化校验模型。

对应 docs/DESIGN.md 中 requirement_analysis 与 test_case 的数据结构,
用于校验 LLM 输出是否满足 prompts/ 下模板里定义的 JSON Schema。
"""
from typing import List, Literal

from pydantic import BaseModel, Field


class RequirementAnalysis(BaseModel):
    feature_points: List[str] = Field(default_factory=list)
    business_rules: List[str] = Field(default_factory=list)
    edge_cases: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)


class CaseStep(BaseModel):
    step: str
    expected: str


class GeneratedTestCase(BaseModel):
    title: str
    precondition: str
    steps: List[CaseStep]
    case_type: Literal["functional", "boundary", "exception"]
    priority: Literal["P0", "P1", "P2"]
    covers: List[str] = Field(default_factory=list)
