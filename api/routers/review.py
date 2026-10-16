from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from models.articles import Article, ArticleStatus
from graph import queries
from pipeline.embedder import embed
from vector.store import upsert_embedding
from worker.lifecycle import publish_article
from core.audit import log_audit
from core.logging import get_logger

logger = get_logger("api.review")

router = APIRouter(prefix="/review", tags=["review"])

# What a reviewer may act on. Superseded articles are history and cannot be changed.
REVIEWABLE = {ArticleStatus.pending_review.value, ArticleStatus.draft.value}
RETRACTABLE = REVIEWABLE | {ArticleStatus.published.value}


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
    previous_article_id: str | None = None


async def _load(article_id: str, tenant_id: str, allowed: set[str]) -> dict[str, Any]:
    article = await queries.get_article_by_id(article_id, tenant_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if article.get("status") not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Article is {article.get('status')} and cannot be changed this way",
        )
    return article


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
    await _load(article_id, tenant_id, REVIEWABLE)

    event_id = await queries.create_review_event_node(
        tenant_id=tenant_id,
        article_id=article_id,
        reviewer_id=request.reviewer_id,
        action="approved",
        note=request.note,
    )
    await publish_article(article_id, tenant_id)

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
    await _load(article_id, tenant_id, RETRACTABLE)

    event_id = await queries.create_review_event_node(
        tenant_id=tenant_id,
        article_id=article_id,
        reviewer_id=request.reviewer_id,
        action="rejected",
        note=request.note,
    )
    await queries.update_article_status(article_id, ArticleStatus.draft.value, tenant_id)

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
    """
    Publish the reviewer's text as a new version. The version being edited is kept as history,
    so the original synthesized text and the human change are both on record.
    """
    original = await _load(article_id, tenant_id, REVIEWABLE)

    edited = Article(
        tenant_id=tenant_id,
        title=original["title"],
        body=request.edited_body,
        version=original.get("version", 1) + 1,
        status=ArticleStatus.pending_review,
        confidence=original.get("confidence", 0.0),
        entity_ids=original.get("entity_ids") or [],
    )
    new_id = await queries.create_article_node(edited)
    await queries.copy_entity_links(article_id, new_id, tenant_id)
    await queries.link_supersedes(new_id, article_id, "Edited by reviewer", tenant_id)

    event_id = await queries.create_review_event_node(
        tenant_id=tenant_id,
        article_id=new_id,
        reviewer_id=request.reviewer_id,
        action="edited",
        edited_body=request.edited_body,
        note=request.note,
    )

    tenant_uuid = UUID(tenant_id)
    embedding = await embed(request.edited_body, tenant_id=tenant_uuid)
    await upsert_embedding(
        article_id=new_id,
        embedding=embedding,
        tenant_id=tenant_uuid,
        metadata={"type": "article", "title": edited.title, "version": edited.version},
    )
    await publish_article(new_id, tenant_id)

    await log_audit(
        tenant_id=tenant_uuid,
        action="article.edit",
        table_name="articles",
        record_id=new_id,
        new_values={"previous_article_id": article_id, "version": edited.version},
    )

    logger.info(
        "Article edited",
        extra={"article_id": new_id, "previous_article_id": article_id, "reviewer_id": request.reviewer_id},
    )

    return ReviewResponse(
        article_id=new_id,
        status=ArticleStatus.published.value,
        event_id=event_id,
        previous_article_id=article_id,
    )
