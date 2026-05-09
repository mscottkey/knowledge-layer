from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ArticleStatus(str, Enum):
    draft = "draft"
    pending_review = "pending_review"
    published = "published"
    superseded = "superseded"


class Article(BaseModel):
    model_config = {"frozen": False}

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    title: str
    body: str
    version: int = Field(default=1, ge=1)
    status: ArticleStatus = Field(default=ArticleStatus.draft)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    entity_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_neo4j_props(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": self.tenant_id,
            "title": self.title,
            "body": self.body,
            "version": self.version,
            "status": self.status.value,
            "confidence": self.confidence,
            "entity_ids": self.entity_ids,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
