"""需求理解 + 用例生成的核心业务逻辑,复用 prompts/ 模板和 app/llm/ 下的公共组件。"""
from typing import Dict, List

from sqlalchemy.orm import Session

from app import models
from app.llm.client import LLMClient, extract_json
from app.llm.output_schemas import GeneratedTestCase, RequirementAnalysis
from app.llm.prompt_loader import load_prompt

GENERATION_STAGES = [
    {"case_type": "functional", "template": "case_gen_functional.jinja2", "source_field": "feature_points"},
    {"case_type": "boundary", "template": "case_gen_boundary.jinja2", "source_field": "business_rules"},
    {"case_type": "exception", "template": "case_gen_exception.jinja2", "source_field": "edge_cases"},
]

PROMPT_VERSION = "v1"


def analyze_requirement(db: Session, requirement: models.Requirement) -> models.RequirementAnalysis:
    """调用 LLM 对需求做结构化拆解,写入/覆盖 requirement_analysis 记录。"""
    client = LLMClient()
    system, user = load_prompt(
        "requirement_analysis.jinja2",
        {"requirement_title": requirement.title, "requirement_content": requirement.content},
    )

    requirement.status = models.RequirementStatus.analyzing.value
    db.commit()

    try:
        result = client.chat(system=system, user=user)
        parsed = RequirementAnalysis(**extract_json(result.content))
    except Exception as e:  # noqa: BLE001 - 需要兜住 LLM 调用/JSON解析/Schema校验的各类异常
        requirement.status = models.RequirementStatus.failed.value
        db.commit()
        raise RuntimeError(f"需求理解失败: {e}") from e

    existing = requirement.analysis
    if existing:
        db.delete(existing)
        db.flush()

    analysis = models.RequirementAnalysis(
        requirement_id=requirement.id,
        feature_points=parsed.feature_points,
        business_rules=parsed.business_rules,
        edge_cases=parsed.edge_cases,
        open_questions=parsed.open_questions,
        raw_llm_output=result.content,
    )
    db.add(analysis)
    requirement.status = models.RequirementStatus.analyzed.value
    db.commit()
    db.refresh(analysis)
    return analysis


def _generate_one_stage(
    db: Session, requirement: models.Requirement, analysis: models.RequirementAnalysis, stage_cfg: Dict
) -> Dict:
    client = LLMClient()
    case_type = stage_cfg["case_type"]

    system, user = load_prompt(
        stage_cfg["template"],
        {
            "requirement_title": requirement.title,
            "requirement_content": requirement.content,
            "feature_points": analysis.feature_points,
            "business_rules": analysis.business_rules,
            "edge_cases": analysis.edge_cases,
        },
    )

    batch = models.GenerationBatch(
        requirement_id=requirement.id,
        case_type=case_type,
        model_name=client.model,
        prompt_version=PROMPT_VERSION,
        status="running",
    )
    db.add(batch)
    db.flush()

    latency_ms = 0.0
    try:
        result = client.chat(system=system, user=user)
        latency_ms = result.latency_ms
        batch.input_tokens = result.input_tokens
        batch.output_tokens = result.output_tokens
        raw_list = extract_json(result.content)
        cases: List[GeneratedTestCase] = [GeneratedTestCase(**item) for item in raw_list]
    except Exception as e:  # noqa: BLE001 - 需要兜住 LLM 调用/解析阶段的各类异常,记录到批次里
        batch.status = "failed"
        batch.error_message = str(e)
        db.commit()
        return {
            "case_type": case_type,
            "generated_count": 0,
            "status": "failed",
            "error_message": str(e),
            "input_tokens": batch.input_tokens,
            "output_tokens": batch.output_tokens,
            "latency_ms": round(latency_ms, 1),
        }

    for item in cases:
        db.add(
            models.TestCase(
                requirement_id=requirement.id,
                gen_batch_id=batch.id,
                title=item.title,
                precondition=item.precondition,
                steps=[s.model_dump() for s in item.steps],
                case_type=item.case_type,
                priority=item.priority,
                covers=item.covers,
            )
        )

    batch.status = "success"
    db.commit()
    return {
        "case_type": case_type,
        "generated_count": len(cases),
        "status": "success",
        "error_message": None,
        "input_tokens": batch.input_tokens,
        "output_tokens": batch.output_tokens,
        "latency_ms": round(latency_ms, 1),
    }


def generate_cases(db: Session, requirement: models.Requirement, case_types: List[str]) -> List[Dict]:
    if not requirement.analysis:
        raise ValueError("请先调用 /analyze 完成需求理解,再生成用例")

    stage_by_type = {s["case_type"]: s for s in GENERATION_STAGES}
    unknown = set(case_types) - set(stage_by_type)
    if unknown:
        raise ValueError(f"不支持的用例类型: {unknown},可选值: {list(stage_by_type)}")

    results = []
    for case_type in case_types:
        results.append(_generate_one_stage(db, requirement, requirement.analysis, stage_by_type[case_type]))
    return results
