from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.deps import ReadAuth
from pipeline.embedder import embed
from vector.store import search_similar
from graph import queries
from core.logging import get_logger

logger = get_logger("api.serve")

router = APIRouter(tags=["serve"])

CANDIDATE_MULTIPLIER = 4


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
    auth: ReadAuth,
    query: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
) -> ContextResponse:
    tenant_id = str(auth.tenant_id)
    query_embedding = await embed(query, tenant_id=auth.tenant_id)

    # Vector search knows nothing about review status, so ask for extra candidates and let the
    # graph keep only published ones. Agents must never see unreviewed or retired content.
    similar_results = await search_similar(
        embedding=query_embedding,
        tenant_id=tenant_id,
        limit=limit * CANDIDATE_MULTIPLIER,
    )

    if not similar_results:
        return ContextResponse(results=[])

    article_ids = [r["id"] for r in similar_results]

    articles = await queries.get_articles_by_ids(article_ids, tenant_id, statuses=["published"])

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
            if len(results) == limit:
                break

    logger.info(
        "Context retrieved",
        extra={
            "tenant_id": tenant_id,
            "query_length": len(query),
            "results_count": len(results),
        },
    )

    return ContextResponse(results=results)
