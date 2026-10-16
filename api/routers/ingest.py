import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import redis.asyncio as redis

from models.signals import KnowledgeSignal, SourceType, SOURCE_AUTHORITY
from worker.processor import SignalProcessor, ProcessResult
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("api.ingest")

router = APIRouter(prefix="/ingest", tags=["ingest"])

_redis_client: redis.Redis | None = None
_mock_queue: dict[str, dict] = {}


async def get_redis() -> redis.Redis | None:
    global _redis_client
    settings = get_settings()

    if settings.mock_stores:
        return None

    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL)

    return _redis_client


class IngestResponse(BaseModel):
    signal_id: str
    status: str


class ProcessResponse(BaseModel):
    article_id: str
    status: str
    confidence: float
    conflict_detected: bool
    entities: list[str]


class DirectSignalRequest(BaseModel):
    tenant_id: str
    source_id: str
    raw_text: str
    metadata: dict[str, Any] | None = None


def map_ticket_payload(payload: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    tenant_id = payload.get("tenant_id", payload.get("account_id", "default"))
    source_id = str(payload.get("ticket_id", payload.get("id", uuid4())))

    description = payload.get("description", "")
    subject = payload.get("subject", "")
    comments = payload.get("comments", [])
    comment_text = "\n\n".join(
        c.get("body", c.get("text", "")) for c in comments if isinstance(c, dict)
    )

    raw_text = f"{subject}\n\n{description}\n\n{comment_text}".strip()

    metadata = {
        "ticket_id": source_id,
        "priority": payload.get("priority"),
        "status": payload.get("status"),
        "tags": payload.get("tags", []),
    }

    return tenant_id, source_id, raw_text, metadata


def map_slack_payload(payload: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    tenant_id = payload.get("tenant_id", payload.get("team_id", "default"))

    event = payload.get("event", payload)
    source_id = event.get("ts", str(uuid4()))
    raw_text = event.get("text", "")

    metadata = {
        "channel": event.get("channel"),
        "user": event.get("user"),
        "thread_ts": event.get("thread_ts"),
    }

    return tenant_id, source_id, raw_text, metadata


def map_pr_payload(payload: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    tenant_id = payload.get("tenant_id", "default")

    pr = payload.get("pull_request", payload)
    source_id = str(pr.get("number", pr.get("id", uuid4())))

    title = pr.get("title", "")
    body = pr.get("body", "")
    raw_text = f"{title}\n\n{body}".strip()

    metadata = {
        "repo": payload.get("repository", {}).get("full_name"),
        "state": pr.get("state"),
        "author": pr.get("user", {}).get("login"),
    }

    return tenant_id, source_id, raw_text, metadata


def map_doc_payload(payload: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    tenant_id = payload.get("tenant_id", "default")
    source_id = payload.get("doc_id", payload.get("id", str(uuid4())))
    raw_text = payload.get("content", payload.get("body", ""))

    metadata = {
        "title": payload.get("title"),
        "url": payload.get("url"),
        "author": payload.get("author"),
    }

    return tenant_id, source_id, raw_text, metadata


def map_call_payload(payload: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    tenant_id = payload.get("tenant_id", "default")
    source_id = payload.get("call_id", str(uuid4()))
    raw_text = payload.get("transcript", payload.get("summary", ""))

    metadata = {
        "duration": payload.get("duration"),
        "participants": payload.get("participants", []),
        "date": payload.get("date"),
    }

    return tenant_id, source_id, raw_text, metadata


SOURCE_MAPPERS = {
    SourceType.ticket: map_ticket_payload,
    SourceType.slack: map_slack_payload,
    SourceType.pr: map_pr_payload,
    SourceType.doc: map_doc_payload,
    SourceType.call: map_call_payload,
}


@router.post("/{source_type}", status_code=202, response_model=IngestResponse)
async def ingest_signal(
    source_type: SourceType,
    payload: dict[str, Any],
) -> IngestResponse:
    mapper = SOURCE_MAPPERS.get(source_type)
    if not mapper:
        raise HTTPException(status_code=400, detail=f"Unknown source type: {source_type}")

    tenant_id, source_id, raw_text, metadata = mapper(payload)

    if not raw_text:
        raise HTTPException(status_code=400, detail="No text content found in payload")

    signal = KnowledgeSignal.from_source(
        tenant_id=tenant_id,
        source=source_type,
        source_id=source_id,
        raw_text=raw_text,
        metadata=metadata,
    )

    settings = get_settings()

    if settings.mock_stores:
        _mock_queue[str(signal.id)] = signal.model_dump(mode="json")
    else:
        redis_client = await get_redis()
        if redis_client:
            await redis_client.lpush(
                "knowledgelayer:signals",
                json.dumps(signal.model_dump(mode="json")),
            )

    logger.info(
        "Signal enqueued",
        extra={"signal_id": str(signal.id), "source": source_type.value},
    )

    return IngestResponse(
        signal_id=str(signal.id),
        status="queued",
    )


@router.post("/process/{signal_id}", response_model=ProcessResponse)
async def process_signal_sync(
    signal_id: str,
    request: DirectSignalRequest,
) -> ProcessResponse:
    signal = KnowledgeSignal(
        tenant_id=request.tenant_id,
        source=SourceType.doc,
        source_id=signal_id,
        raw_text=request.raw_text,
        authority=SOURCE_AUTHORITY[SourceType.doc],
        metadata=request.metadata or {},
    )

    processor = SignalProcessor()
    result = await processor.process(signal)

    return ProcessResponse(
        article_id=result.article_id,
        status=result.status.value,
        confidence=result.confidence,
        conflict_detected=result.conflict_detected,
        entities=result.entities,
    )
