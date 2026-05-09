from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ReviewAction(str, Enum):
    approved = "approved"
    edited = "edited"
    rejected = "rejected"


class ReviewEvent(BaseModel):
    model_config = {"frozen": False}

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    article_id: str
    reviewer_id: str
    action: ReviewAction
    edited_body: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_neo4j_props(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": self.tenant_id,
            "article_id": self.article_id,
            "reviewer_id": self.reviewer_id,
            "action": self.action.value,
            "edited_body": self.edited_body,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
        }
