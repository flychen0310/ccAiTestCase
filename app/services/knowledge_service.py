"""RAG 知识库的入库、检索、从已采纳用例批量导入逻辑。"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app import models
from app.llm.retrieval import compute_openai_embedding, needs_precomputed_embedding, retrieve_top_k

MIN_SCORE = 0.05  # 低于这个相似度基本等于不相关,过滤掉避免噪音examples


def add_document(
    db: Session,
    doc_type: str,
    content: str,
    metadata: Optional[dict] = None,
    commit: bool = True,
) -> models.KnowledgeDoc:
    """新增一条知识库文档。

    commit=False 用于批量导入场景:调用方把多条 add 完后统一 commit 一次,
    避免逐条提交带来的多次事务开销。
    """
    doc = models.KnowledgeDoc(doc_type=doc_type, content=content, metadata_=metadata or {})
    if needs_precomputed_embedding():
        doc.embedding = compute_openai_embedding(content)
        doc.embedding_model = "text-embedding-3-small"
    db.add(doc)
    if commit:
        db.commit()
        db.refresh(doc)
    return doc


def retrieve(
    db: Session,
    query: str,
    doc_type: Optional[str] = None,
    top_k: int = 3,
    exclude_requirement_id: Optional[int] = None,
) -> List[models.KnowledgeDoc]:
    """检索最相关的知识库文档。

    exclude_requirement_id: 排除来自该需求自己的样例。生成用例时应该传当前需求 id,
    否则"刚生成的用例被导入知识库"和"下一次生成检索到它自己"会导致同需求内自我复读,
    而不是真正参考其他需求积累的经验。
    """
    q = db.query(models.KnowledgeDoc)
    if doc_type:
        q = q.filter(models.KnowledgeDoc.doc_type == doc_type)
    docs = q.all()
    if exclude_requirement_id is not None:
        docs = [d for d in docs if d.metadata_.get("requirement_id") != exclude_requirement_id]
    if not docs:
        return []

    ranked = retrieve_top_k(
        query=query,
        documents=[d.content for d in docs],
        embeddings=[d.embedding for d in docs],
        top_k=top_k,
    )
    return [docs[idx] for idx, score in ranked if score >= MIN_SCORE]


def _format_case_as_doc(case: models.TestCase) -> str:
    step_lines = [f"  {i + 1}. 操作: {s['step']} | 预期: {s['expected']}" for i, s in enumerate(case.steps)]
    return (
        f"标题: {case.title}\n"
        f"用例类型: {case.case_type}\n"
        f"前置条件: {case.precondition or '无'}\n"
        f"步骤:\n" + "\n".join(step_lines)
    )


def import_accepted_cases(db: Session, requirement_id: Optional[int] = None) -> dict:
    """把 review_status=accepted 的用例导入知识库,作为后续生成的参考样例。

    通过 metadata.source_case_id 避免重复导入同一条用例。
    """
    query = db.query(models.TestCase).filter(models.TestCase.review_status == models.ReviewStatus.accepted.value)
    if requirement_id:
        query = query.filter(models.TestCase.requirement_id == requirement_id)
    cases = query.all()

    existing_source_ids = {
        doc.metadata_.get("source_case_id")
        for doc in db.query(models.KnowledgeDoc).filter(models.KnowledgeDoc.doc_type == "test_case_sample").all()
    }

    imported, skipped = 0, 0
    for case in cases:
        if case.id in existing_source_ids:
            skipped += 1
            continue
        add_document(
            db,
            doc_type="test_case_sample",
            content=_format_case_as_doc(case),
            metadata={
                "source_case_id": case.id,
                "requirement_id": case.requirement_id,
                "case_type": case.case_type,
            },
            commit=False,
        )
        imported += 1

    if imported:
        db.commit()

    return {"imported": imported, "skipped_existing": skipped, "total_accepted": len(cases)}
