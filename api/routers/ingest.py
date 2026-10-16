from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import WriteAuth
from models.signals import KnowledgeSignal, SourceType, SOURCE_AUTHORITY
from worker import queue
from worker.processor import SignalProcessor
from core.logging import get_logger

logger = get_logger("api.ingest")

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Every signal costs an embedding and a synthesis call, so refuse oversized payloads up front.
MAX_SIGNAL_CHARS = 50_000


class IngestResponse(BaseModel):
    signal_id: str
    status: str


class ProcessResponse(BaseModel):
    article_id: str
    # "published", "pending_review", or "duplicate" when the signal added nothing new.
    status: str
    confidence: float
    conflict_detected: bool
    entities: list[str]


class DirectSignalRequest(BaseModel):
    source_id: str
    raw_text: str = Field(max_length=MAX_SIGNAL_CHARS)
    source: SourceType = SourceType.doc
    metadata: dict[str, Any] | None = None
    # Accepted for backwards compatibility. The tenant comes from the API key, and a different
    # one here is refused.
    tenant_id: str | None = None


def map_ticket_payload(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
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

    return source_id, raw_text, metadata


def map_slack_payload(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:

    event = payload.get("event", payload)
    source_id = event.get("ts", str(uuid4()))
    raw_text = event.get("text", "")

    metadata = {
        "channel": event.get("channel"),
        "user": event.get("user"),
        "thread_ts": event.get("thread_ts"),
    }

    return source_id, raw_text, metadata


def map_pr_payload(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:

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

    return source_id, raw_text, metadata


def map_doc_payload(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    source_id = payload.get("doc_id", payload.get("id", str(uuid4())))
    raw_text = payload.get("content", payload.get("body", ""))

    metadata = {
        "title": payload.get("title"),
        "url": payload.get("url"),
        "author": payload.get("author"),
    }

    return source_id, raw_text, metadata


def map_call_payload(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    source_id = payload.get("call_id", str(uuid4()))
    raw_text = payload.get("transcript", payload.get("summary", ""))

    metadata = {
        "duration": payload.get("duration"),
        "participants": payload.get("participants", []),
        "date": payload.get("date"),
    }

    return source_id, raw_text, metadata


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
    auth: WriteAuth,
) -> IngestResponse:
    mapper = SOURCE_MAPPERS.get(source_type)
    if not mapper:
        raise HTTPException(status_code=400, detail=f"Unknown source type: {source_type}")

    source_id, raw_text, metadata = mapper(payload)

    if not raw_text:
        raise HTTPException(status_code=400, detail="No text content found in payload")
    if len(raw_text) > MAX_SIGNAL_CHARS:
        raise HTTPException(status_code=413, detail=f"Signal text is over {MAX_SIGNAL_CHARS} characters")

    signal = KnowledgeSignal.from_source(
        tenant_id=str(auth.tenant_id),
        source=source_type,
        source_id=source_id,
        raw_text=raw_text,
        metadata=metadata,
    )
    await queue.enqueue(signal)

    logger.info(
        "Signal enqueued",
        extra={"signal_id": str(signal.id), "source": source_type.value, "tenant_id": signal.tenant_id},
    )

    return IngestResponse(signal_id=str(signal.id), status="queued")


@router.post("/process/{signal_id}", response_model=ProcessResponse)
async def process_signal_sync(
    signal_id: str,
    request: DirectSignalRequest,
    auth: WriteAuth,
) -> ProcessResponse:
    """Run the pipeline on the supplied text now, without the queue. For development and testing."""
    if request.tenant_id is not None and request.tenant_id != str(auth.tenant_id):
        raise HTTPException(status_code=403, detail="tenant_id does not match the API key's tenant")

    try:
        signal_uuid = UUID(signal_id)
    except ValueError:
        signal_uuid = uuid4()

    signal = KnowledgeSignal(
        id=signal_uuid,
        tenant_id=str(auth.tenant_id),
        source=request.source,
        source_id=request.source_id,
        raw_text=request.raw_text,
        authority=SOURCE_AUTHORITY[request.source],
        metadata=request.metadata or {},
    )

    result = await SignalProcessor().process(signal, user_id=auth.user_id)

    return ProcessResponse(
        article_id=result.article_id,
        status="duplicate" if result.duplicate else result.status.value,
        confidence=result.confidence,
        conflict_detected=result.conflict_detected,
        entities=result.entities,
    )
