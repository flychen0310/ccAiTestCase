"""效果验证用的轻量指标计算。

覆盖率/召回率的匹配方式采用模糊匹配,这是一个近似启发式指标,
用于快速筛选生成效果明显不合格的 case,不能替代人工评审,只作为回归测试中的"预警信号"。

匹配分数取两种算法的较大值:
  - SequenceMatcher.ratio():对语序、句式相近的表述敏感(适合检测局部改写)
  - 字符集合重叠系数(overlap coefficient):中文短语换一种说法表达同一件事时,
    逐字符 SequenceMatcher 容易打低分(例如"库存为0时加号按钮是否可用" vs
    "库存为0的商品在购物车中的数量显示与操作"),字符集合重叠对这种"同义改写"更鲁棒。
单独使用字符集合重叠系数会有把"已过期"和"已使用过"这类不同场景误判为同一条的风险,
所以两者取较大值只作为召回的辅助信号,不作为唯一判据。
"""
import re
from difflib import SequenceMatcher
from typing import List, Tuple

MATCH_THRESHOLD = 0.45

_CLEAN_RE = re.compile(r"[,,。()()\s]")


def _char_overlap(a: str, b: str) -> float:
    a_chars, b_chars = set(_CLEAN_RE.sub("", a)), set(_CLEAN_RE.sub("", b))
    if not a_chars or not b_chars:
        return 0.0
    return len(a_chars & b_chars) / min(len(a_chars), len(b_chars))


def _similarity(a: str, b: str) -> float:
    return max(SequenceMatcher(None, a, b).ratio(), _char_overlap(a, b))


def best_match(item: str, candidates: List[str]) -> Tuple[float, str]:
    if not candidates:
        return 0.0, ""
    scored = [(_similarity(item, c), c) for c in candidates]
    return max(scored, key=lambda x: x[0])


def recall_score(golden: List[str], predicted: List[str], threshold: float = MATCH_THRESHOLD) -> dict:
    """golden 中有多少条能在 predicted 里找到相似表述,用于评估"需求理解"阶段的召回。"""
    matched, missed = [], []
    for g in golden:
        score, match = best_match(g, predicted)
        (matched if score >= threshold else missed).append(
            {"golden": g, "best_match": match, "score": round(score, 3)}
        )
    total = len(golden) or 1
    return {
        "recall_rate": round(len(matched) / total, 3),
        "matched": matched,
        "missed": missed,
    }


def coverage_score(source_items: List[str], covers_lists: List[List[str]], threshold: float = MATCH_THRESHOLD) -> dict:
    """source_items(如 feature_points/business_rules/edge_cases)有多少条被生成用例的 covers 字段引用到。"""
    all_covers = [c for covers in covers_lists for c in covers]
    matched, missed = [], []
    for item in source_items:
        score, match = best_match(item, all_covers)
        (matched if score >= threshold else missed).append(
            {"source": item, "best_match": match, "score": round(score, 3)}
        )
    total = len(source_items) or 1
    return {
        "coverage_rate": round(len(matched) / total, 3),
        "matched": matched,
        "missed": missed,
    }
