from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class APIKey(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None = None
    key_prefix: str
    scopes: list[str] = Field(default_factory=lambda: ["read"])
    rate_limit_rpm: int = 1000
    last_used_at: datetime | None = None
    total_requests: int = 0
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    created_by: UUID | None = None


class APIKeyCreate(BaseModel):
    name: str
    description: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["read"])
    expires_at: datetime | None = None


class APIKeyWithSecret(APIKey):
    """Returned only on creation - includes the unhashed key."""
    key: str
