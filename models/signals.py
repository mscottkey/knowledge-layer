from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    ticket = "ticket"
    slack = "slack"
    pr = "pr"
    call = "call"
    doc = "doc"


SOURCE_AUTHORITY: dict[SourceType, float] = {
    SourceType.ticket: 0.7,
    SourceType.slack: 0.5,
    SourceType.pr: 1.0,
    SourceType.call: 0.6,
    SourceType.doc: 0.8,
}


class KnowledgeSignal(BaseModel):
    model_config = {"frozen": False}

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    source: SourceType
    source_id: str
    raw_text: str
    authority: float = Field(default=0.5, ge=0.0, le=1.0)
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_source(
        cls,
        tenant_id: str,
        source: SourceType,
        source_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> "KnowledgeSignal":
        return cls(
            tenant_id=tenant_id,
            source=source,
            source_id=source_id,
            raw_text=raw_text,
            authority=SOURCE_AUTHORITY.get(source, 0.5),
            metadata=metadata or {},
        )
