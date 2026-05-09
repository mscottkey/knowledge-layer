from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from pipeline.embedder import embed
from vector.store import search_similar
from graph import queries
from core.logging import get_logger

logger = get_logger("api.serve")

router = APIRouter(tags=["serve"])


class ArticleResult(BaseModel):
    article_id: str
    title: str
    body: str
    confidence: float
    version: int


class ContextResponse(BaseModel):
    results: list[ArticleResult]


@router.get("/context", response_model=ContextResponse)
async def get_context(
    query: str = Query(..., min_length=1),
    tenant_id: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
) -> ContextResponse:
    query_embedding = await embed(query)

    similar_results = await search_similar(
        embedding=query_embedding,
        tenant_id=tenant_id,
        limit=limit,
    )

    if not similar_results:
        return ContextResponse(results=[])

    article_ids = [r["id"] for r in similar_results]

    articles = await queries.get_articles_by_ids(article_ids, tenant_id)

    article_map = {a["id"]: a for a in articles}

    results = []
    for r in similar_results:
        article = article_map.get(r["id"])
        if article:
            results.append(ArticleResult(
                article_id=article["id"],
                title=article.get("title", ""),
                body=article.get("body", ""),
                confidence=article.get("confidence", 0.0),
                version=article.get("version", 1),
            ))

    logger.info(
        "Context retrieved",
        extra={
            "tenant_id": tenant_id,
            "query_length": len(query),
            "results_count": len(results),
        },
    )

    return ContextResponse(results=results)
