"""Prompt 效果验证脚本。

用法:
    # 真实调用(需先配置 .env,见 .env.example)
    python eval/run_eval.py

    # 不调用真实 API,用构造的 mock 数据跑通整条 pipeline 和指标计算逻辑
    python eval/run_eval.py --mock

跑完后:
    - 终端打印每条需求的分析召回率、各类型用例覆盖率、schema 校验通过率、token 用量
    - eval/results/<req_id>/ 下保存每个阶段的原始输出,便于人工抽查用例质量
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm.client import LLMClient, extract_json
from app.llm.output_schemas import GeneratedTestCase as TestCase
from app.llm.output_schemas import RequirementAnalysis
from app.llm.prompt_loader import load_prompt
from eval.metrics import coverage_score, recall_score

EVAL_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVAL_DIR / "dataset"
RESULTS_DIR = EVAL_DIR / "results"

GENERATION_STAGES = [
    {
        "case_type": "functional",
        "template": "case_gen_functional.jinja2",
        "source_field": "feature_points",
    },
    {
        "case_type": "boundary",
        "template": "case_gen_boundary.jinja2",
        "source_field": "business_rules",
    },
    {
        "case_type": "exception",
        "template": "case_gen_exception.jinja2",
        "source_field": "edge_cases",
    },
]


def build_mock_analysis_response(req: Dict) -> str:
    golden = req["golden"]
    payload = {
        "feature_points": golden["feature_points"],
        "business_rules": golden["business_rules"],
        "edge_cases": golden["edge_cases"],
        "open_questions": [],
    }
    return json.dumps(payload, ensure_ascii=False)


def build_mock_case_response(source_items: List[str], case_type: str) -> str:
    cases = []
    for item in source_items:
        cases.append(
            {
                "title": f"[mock]针对'{item}'的{case_type}用例",
                "precondition": "mock 前置条件",
                "steps": [{"step": "mock 操作步骤", "expected": "mock 预期结果"}],
                "case_type": case_type,
                "priority": "P1",
                "covers": [item],
            }
        )
    return json.dumps(cases, ensure_ascii=False)


def call_stage(
    client: LLMClient,
    template: str,
    variables: Dict,
    mock_response: str = "",
    stage_name: str = "",
    max_retries: int = 4,
    backoff_base_sec: float = 8.0,
) -> Dict:
    system, user = load_prompt(template, variables)
    last_err = None
    for attempt in range(1, max_retries + 1):
        suffix = f"(第{attempt}次)" if attempt > 1 else ""
        print(f"    -> 调用 {stage_name}{suffix} ...", end=" ", flush=True)
        try:
            result = client.chat(system=system, user=user, mock_response=mock_response)
            print(
                f"完成 ({round(result.latency_ms, 1)}ms, tokens {result.input_tokens}/{result.output_tokens})",
                flush=True,
            )
            return {
                "system": system,
                "user": user,
                "raw_content": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": round(result.latency_ms, 1),
                "model": result.model,
            }
        except Exception as e:  # noqa: BLE001 - 需要兜住供应商侧的各种瞬时错误(503/超时/限流)
            last_err = e
            wait = backoff_base_sec * attempt
            print(f"失败({e.__class__.__name__}: {e}),{wait:.0f}s 后重试", flush=True)
            if attempt < max_retries:
                time.sleep(wait)

    print(f"    !! {stage_name} 重试{max_retries}次后仍失败,记录为空结果继续后续流程", flush=True)
    return {
        "system": system,
        "user": user,
        "raw_content": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 0.0,
        "model": client.model,
        "call_error": str(last_err),
    }


def run_one_requirement(req: Dict, client: LLMClient, use_mock: bool) -> Dict:
    req_id = req["id"]
    result_dir = RESULTS_DIR / req_id
    result_dir.mkdir(parents=True, exist_ok=True)

    # ---- 阶段1:需求理解 ----
    mock_analysis = build_mock_analysis_response(req) if use_mock else ""
    analysis_stage = call_stage(
        client,
        "requirement_analysis.jinja2",
        {"requirement_title": req["title"], "requirement_content": req["content"]},
        mock_response=mock_analysis,
        stage_name="需求理解",
    )
    (result_dir / "01_analysis_raw.json").write_text(
        json.dumps(analysis_stage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    analysis_valid = False
    analysis: RequirementAnalysis
    try:
        parsed = extract_json(analysis_stage["raw_content"])
        analysis = RequirementAnalysis(**parsed)
        analysis_valid = True
    except (json.JSONDecodeError, ValidationError) as e:
        analysis = RequirementAnalysis()
        analysis_stage["parse_error"] = str(e)

    feature_point_recall = recall_score(req["golden"]["feature_points"], analysis.feature_points)
    edge_case_recall = recall_score(req["golden"]["edge_cases"], analysis.edge_cases)

    # ---- 阶段2:分类型用例生成 ----
    generation_report = {}
    all_cases: List[TestCase] = []
    source_map = {
        "feature_points": analysis.feature_points,
        "business_rules": analysis.business_rules,
        "edge_cases": analysis.edge_cases,
    }

    for stage_cfg in GENERATION_STAGES:
        case_type = stage_cfg["case_type"]
        source_items = source_map[stage_cfg["source_field"]]
        mock_cases = build_mock_case_response(source_items, case_type) if use_mock else ""

        stage_result = call_stage(
            client,
            stage_cfg["template"],
            {
                "requirement_title": req["title"],
                "requirement_content": req["content"],
                "feature_points": analysis.feature_points,
                "business_rules": analysis.business_rules,
                "edge_cases": analysis.edge_cases,
            },
            mock_response=mock_cases,
            stage_name=f"用例生成[{case_type}]",
        )
        (result_dir / f"02_{case_type}_raw.json").write_text(
            json.dumps(stage_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        valid_cases, schema_errors = [], []
        try:
            raw_list = extract_json(stage_result["raw_content"])
            for idx, item in enumerate(raw_list):
                try:
                    valid_cases.append(TestCase(**item))
                except ValidationError as e:
                    schema_errors.append({"index": idx, "error": str(e)})
        except json.JSONDecodeError as e:
            schema_errors.append({"index": None, "error": f"JSON解析失败: {e}"})

        all_cases.extend(valid_cases)
        total_generated = len(valid_cases) + len(schema_errors)
        schema_pass_rate = round(len(valid_cases) / total_generated, 3) if total_generated else 0.0

        cov = coverage_score(source_items, [c.covers for c in valid_cases])

        generation_report[case_type] = {
            "generated_count": len(valid_cases),
            "schema_pass_rate": schema_pass_rate,
            "schema_errors": schema_errors,
            "coverage_rate": cov["coverage_rate"],
            "missed_source_items": cov["missed"],
            "input_tokens": stage_result["input_tokens"],
            "output_tokens": stage_result["output_tokens"],
            "latency_ms": stage_result["latency_ms"],
        }

    (result_dir / "03_final_cases.json").write_text(
        json.dumps([c.model_dump() for c in all_cases], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = {
        "req_id": req_id,
        "title": req["title"],
        "analysis": {
            "schema_valid": analysis_valid,
            "feature_point_recall_rate": feature_point_recall["recall_rate"],
            "edge_case_recall_rate": edge_case_recall["recall_rate"],
            "missed_feature_points": feature_point_recall["missed"],
            "missed_edge_cases": edge_case_recall["missed"],
            "input_tokens": analysis_stage["input_tokens"],
            "output_tokens": analysis_stage["output_tokens"],
            "latency_ms": analysis_stage["latency_ms"],
        },
        "generation": generation_report,
        "total_cases": len(all_cases),
    }
    (result_dir / "00_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def print_summary(reports: List[Dict]) -> None:
    print("\n" + "=" * 100)
    print("Prompt 效果验证汇总报告")
    print("=" * 100)
    for r in reports:
        print(f"\n【{r['req_id']}】{r['title']}")
        a = r["analysis"]
        print(
            f"  需求理解: schema_valid={a['schema_valid']}  "
            f"功能点召回率={a['feature_point_recall_rate']}  "
            f"异常场景召回率={a['edge_case_recall_rate']}  "
            f"tokens(in/out)={a['input_tokens']}/{a['output_tokens']}  "
            f"耗时={a['latency_ms']}ms"
        )
        for case_type, g in r["generation"].items():
            print(
                f"  用例生成[{case_type}]: 生成数={g['generated_count']}  "
                f"schema通过率={g['schema_pass_rate']}  "
                f"覆盖率={g['coverage_rate']}  "
                f"tokens(in/out)={g['input_tokens']}/{g['output_tokens']}  "
                f"耗时={g['latency_ms']}ms"
            )
        print(f"  用例总数: {r['total_cases']}")
    print("\n" + "=" * 100)
    print(f"详细结果已保存至: {RESULTS_DIR}")
    print("=" * 100)


def main():
    parser = argparse.ArgumentParser(description="AI 测试用例生成 Prompt 效果验证")
    parser.add_argument("--mock", action="store_true", help="不调用真实 LLM API,用构造数据跑通 pipeline 逻辑")
    parser.add_argument(
        "--dataset",
        default=None,
        help="指定单个数据集文件名(位于 eval/dataset/),不指定则跑全部",
    )
    args = parser.parse_args()

    load_dotenv()

    provider = "mock" if args.mock else None
    client = LLMClient(provider=provider)

    if args.dataset:
        dataset_files = [DATASET_DIR / args.dataset]
    else:
        dataset_files = sorted(DATASET_DIR.glob("*.json"))

    if not dataset_files:
        print(f"未在 {DATASET_DIR} 找到数据集文件")
        return

    reports = []
    for f in dataset_files:
        req = json.loads(f.read_text(encoding="utf-8"))
        print(f"正在处理: {req['id']} ...", flush=True)
        report = run_one_requirement(req, client, use_mock=args.mock)
        reports.append(report)

    print_summary(reports)


if __name__ == "__main__":
    main()
