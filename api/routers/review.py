from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from models.articles import ArticleStatus
from graph import queries
from core.logging import get_logger

logger = get_logger("api.review")

router = APIRouter(prefix="/review", tags=["review"])


class ReviewQueueItem(BaseModel):
    article_id: str
    title: str
    body: str
    version: int
    confidence: float
    created_at: str


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]


class EditRequest(BaseModel):
    edited_body: str
    reviewer_id: str
    note: str | None = None


class ReviewRequest(BaseModel):
    reviewer_id: str
    note: str | None = None


class ReviewResponse(BaseModel):
    article_id: str
    status: str
    event_id: str


@router.get("/queue", response_model=ReviewQueueResponse)
async def get_review_queue(
    tenant_id: str = Query(..., min_length=1),
) -> ReviewQueueResponse:
    articles = await queries.get_pending_review_articles(tenant_id)

    items = [
        ReviewQueueItem(
            article_id=a["id"],
            title=a.get("title", ""),
            body=a.get("body", ""),
            version=a.get("version", 1),
            confidence=a.get("confidence", 0.0),
            created_at=a.get("created_at", ""),
        )
        for a in articles
    ]

    logger.info(
        "Review queue fetched",
        extra={"tenant_id": tenant_id, "count": len(items)},
    )

    return ReviewQueueResponse(items=items)


@router.post("/{article_id}/approve", response_model=ReviewResponse)
async def approve_article(
    article_id: str,
    request: ReviewRequest,
    tenant_id: str = Query(..., min_length=1),
) -> ReviewResponse:
    article = await queries.get_article_by_id(article_id, tenant_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    await queries.update_article_status(article_id, ArticleStatus.published.value, tenant_id)

    event_id = await queries.create_review_event_node(
        tenant_id=tenant_id,
        article_id=article_id,
        reviewer_id=request.reviewer_id,
        action="approved",
        note=request.note,
    )

    logger.info(
        "Article approved",
        extra={"article_id": article_id, "reviewer_id": request.reviewer_id},
    )

    return ReviewResponse(
        article_id=article_id,
        status=ArticleStatus.published.value,
        event_id=event_id,
    )


@router.post("/{article_id}/reject", response_model=ReviewResponse)
async def reject_article(
    article_id: str,
    request: ReviewRequest,
    tenant_id: str = Query(..., min_length=1),
) -> ReviewResponse:
    article = await queries.get_article_by_id(article_id, tenant_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    await queries.update_article_status(article_id, ArticleStatus.draft.value, tenant_id)

    event_id = await queries.create_review_event_node(
        tenant_id=tenant_id,
        article_id=article_id,
        reviewer_id=request.reviewer_id,
        action="rejected",
        note=request.note,
    )

    logger.info(
        "Article rejected",
        extra={"article_id": article_id, "reviewer_id": request.reviewer_id},
    )

    return ReviewResponse(
        article_id=article_id,
        status=ArticleStatus.draft.value,
        event_id=event_id,
    )


@router.post("/{article_id}/edit", response_model=ReviewResponse)
async def edit_article(
    article_id: str,
    request: EditRequest,
    tenant_id: str = Query(..., min_length=1),
) -> ReviewResponse:
    article = await queries.get_article_by_id(article_id, tenant_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    await queries.update_article_status(article_id, ArticleStatus.published.value, tenant_id)

    event_id = await queries.create_review_event_node(
        tenant_id=tenant_id,
        article_id=article_id,
        reviewer_id=request.reviewer_id,
        action="edited",
        edited_body=request.edited_body,
        note=request.note,
    )

    logger.info(
        "Article edited",
        extra={"article_id": article_id, "reviewer_id": request.reviewer_id},
    )

    return ReviewResponse(
        article_id=article_id,
        status=ArticleStatus.published.value,
        event_id=event_id,
    )
