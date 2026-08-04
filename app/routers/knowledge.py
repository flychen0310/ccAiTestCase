from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import api_schemas, models
from app.database import get_db
from app.services import knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("/documents", response_model=api_schemas.KnowledgeDocOut)
def create_document(payload: api_schemas.KnowledgeDocCreate, db: Session = Depends(get_db)):
    try:
        return knowledge_service.add_document(db, payload.doc_type, payload.content, payload.metadata)
    except Exception as e:  # noqa: BLE001 - openai embedding 调用失败时给出明确提示
        raise HTTPException(status_code=502, detail=f"写入知识库失败: {e}") from e


@router.get("/documents", response_model=List[api_schemas.KnowledgeDocOut])
def list_documents(
    doc_type: Optional[str] = None,
    query: Optional[str] = None,
    top_k: int = 10,
    db: Session = Depends(get_db),
):
    if query:
        return knowledge_service.retrieve(db, query, doc_type=doc_type, top_k=top_k)
    q = db.query(models.KnowledgeDoc)
    if doc_type:
        q = q.filter(models.KnowledgeDoc.doc_type == doc_type)
    return q.order_by(models.KnowledgeDoc.id.desc()).limit(top_k).all()


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.KnowledgeDoc, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="知识库文档不存在")
    db.delete(doc)
    db.commit()


@router.post("/import-accepted-cases", response_model=api_schemas.ImportAcceptedCasesResponse)
def import_accepted_cases(payload: api_schemas.ImportAcceptedCasesRequest, db: Session = Depends(get_db)):
    return knowledge_service.import_accepted_cases(db, payload.requirement_id)
