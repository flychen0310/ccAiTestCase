"""RAG 检索抽象层。

DeepSeek 目前没有 embedding 接口,为了让 RAG 不强依赖某个供应商,提供两种检索方式:
  - "tfidf" (默认): 基于字符 n-gram 的 TF-IDF + 余弦相似度,纯本地计算,无需任何 API key,
    对中文短文本效果足够,零调用成本。语料规模变大后检索会变慢(每次查询都重新 fit),
    但对知识库这种量级(几百~几千条)完全可以接受。
  - "openai": 用 OpenAI embedding 接口算语义向量,语义检索效果更好,需要配置 OPENAI_API_KEY。
    向量以 JSON 数组形式存进 knowledge_doc.embedding,检索时用 numpy 算余弦相似度。

通过环境变量 RAG_EMBEDDING_PROVIDER 切换(tfidf / openai)。
"""
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

EMBEDDING_MODEL_OPENAI = "text-embedding-3-small"


@dataclass
class ScoredDoc:
    index: int
    score: float


def get_retrieval_provider() -> str:
    return os.getenv("RAG_EMBEDDING_PROVIDER", "tfidf").lower()


def needs_precomputed_embedding(provider: Optional[str] = None) -> bool:
    """openai 模式下入库时需要预先算好并存储向量;tfidf 模式不需要,检索时即时计算。"""
    return (provider or get_retrieval_provider()) == "openai"


def compute_openai_embedding(text: str) -> List[float]:
    from openai import OpenAI

    client = OpenAI()
    resp = client.embeddings.create(model=EMBEDDING_MODEL_OPENAI, input=text)
    return resp.data[0].embedding


def rank_by_openai_embedding(query: str, doc_embeddings: List[Optional[List[float]]]) -> List[ScoredDoc]:
    query_vec = np.array(compute_openai_embedding(query)).reshape(1, -1)
    valid = [(i, e) for i, e in enumerate(doc_embeddings) if e]
    if not valid:
        return []
    indices, vectors = zip(*valid)
    sims = cosine_similarity(query_vec, np.array(vectors))[0]
    return sorted(
        (ScoredDoc(index=idx, score=float(score)) for idx, score in zip(indices, sims)),
        key=lambda d: d.score,
        reverse=True,
    )


def rank_by_tfidf(query: str, documents: List[str]) -> List[ScoredDoc]:
    """对 query + 语料整体重新拟合 TF-IDF,返回按相似度降序排列的文档下标。"""
    if not documents:
        return []
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 3))
    corpus = documents + [query]
    tfidf = vectorizer.fit_transform(corpus)
    query_vec, doc_vecs = tfidf[-1], tfidf[:-1]
    sims = cosine_similarity(query_vec, doc_vecs)[0]
    return sorted(
        (ScoredDoc(index=i, score=float(s)) for i, s in enumerate(sims)),
        key=lambda d: d.score,
        reverse=True,
    )


def retrieve_top_k(
    query: str, documents: List[str], embeddings: List[Optional[List[float]]], top_k: int = 3
) -> List[Tuple[int, float]]:
    """统一入口:根据配置的 provider 选择检索方式,返回 [(文档下标, 相似度分数), ...]。"""
    provider = get_retrieval_provider()
    if provider == "openai":
        ranked = rank_by_openai_embedding(query, embeddings)
    else:
        ranked = rank_by_tfidf(query, documents)
    return [(d.index, d.score) for d in ranked[:top_k]]
