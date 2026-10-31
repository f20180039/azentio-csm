"""Approved Product Knowledge and FAQ search endpoint (Task C6)."""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from app.store import store

router = APIRouter(tags=["FAQ"])


class FAQItem(BaseModel):
    id: str
    question: str
    answer: str
    score: float


class FAQSearchResponse(BaseModel):
    items: list[FAQItem]


@router.get("/faq/search", response_model=FAQSearchResponse)
async def search_faq(
    q: str = Query("", description="Natural language search query"),
    limit: int = Query(3, ge=1, le=10, description="Max results to return"),
) -> FAQSearchResponse:
    """Full-text search over approved banking product FAQs using SQLite FTS5 (BM25 with Porter stemming).

    Returns items ordered by relevance score. Results below the relevance threshold are dropped.
    An empty items list signals that the query is unsupported by the approved FAQ knowledge base.
    """
    results = store.search_faq(query=q, limit=limit)
    return FAQSearchResponse(items=[FAQItem(**item) for item in results])
