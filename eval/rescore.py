"""用改进后的 metrics 算法,基于已缓存的 raw_content 重新计算 00_report.json,
不重新调用 LLM API。仅用于迭代评分算法时快速复核,不是常规评测流程的一部分。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm.client import extract_json
from app.llm.output_schemas import GeneratedTestCase as TestCase
from app.llm.output_schemas import RequirementAnalysis
from eval.metrics import coverage_score, recall_score

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

GENERATION_STAGES = [
    {"case_type": "functional", "source_field": "feature_points"},
    {"case_type": "boundary", "source_field": "business_rules"},
    {"case_type": "exception", "source_field": "edge_cases"},
]


def main():
    for req_file in sorted(DATASET_DIR.glob("*.json")):
        req = json.loads(req_file.read_text(encoding="utf-8"))
        rid = req["id"]
        rd = RESULTS_DIR / rid
        if not (rd / "01_analysis_raw.json").exists():
            continue

        analysis_raw = json.loads((rd / "01_analysis_raw.json").read_text(encoding="utf-8"))
        analysis = RequirementAnalysis(**extract_json(analysis_raw["raw_content"]))

        fp_recall = recall_score(req["golden"]["feature_points"], analysis.feature_points)
        ec_recall = recall_score(req["golden"]["edge_cases"], analysis.edge_cases)

        source_map = {
            "feature_points": analysis.feature_points,
            "business_rules": analysis.business_rules,
            "edge_cases": analysis.edge_cases,
        }

        generation_report = {}
        total_cases = 0
        for stage_cfg in GENERATION_STAGES:
            case_type = stage_cfg["case_type"]
            raw = json.loads((rd / f"02_{case_type}_raw.json").read_text(encoding="utf-8"))
            cases = [TestCase(**item) for item in extract_json(raw["raw_content"])]
            total_cases += len(cases)
            cov = coverage_score(source_map[stage_cfg["source_field"]], [c.covers for c in cases])
            generation_report[case_type] = {
                "generated_count": len(cases),
                "coverage_rate": cov["coverage_rate"],
                "missed_source_items": cov["missed"],
                "input_tokens": raw["input_tokens"],
                "output_tokens": raw["output_tokens"],
                "latency_ms": raw["latency_ms"],
            }

        report = {
            "req_id": rid,
            "title": req["title"],
            "analysis": {
                "feature_point_recall_rate": fp_recall["recall_rate"],
                "edge_case_recall_rate": ec_recall["recall_rate"],
                "missed_feature_points": fp_recall["missed"],
                "missed_edge_cases": ec_recall["missed"],
                "input_tokens": analysis_raw["input_tokens"],
                "output_tokens": analysis_raw["output_tokens"],
                "latency_ms": analysis_raw["latency_ms"],
            },
            "generation": generation_report,
            "total_cases": total_cases,
        }
        (rd / "00_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"【{rid}】功能点召回率={fp_recall['recall_rate']}  异常场景召回率={ec_recall['recall_rate']}  用例总数={total_cases}")


if __name__ == "__main__":
    main()
