from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class TenantStatus(str, Enum):
    active = "active"
    suspended = "suspended"
    pending_deletion = "pending_deletion"


class DataRegion(str, Enum):
    us = "us"
    eu = "eu"
    ap = "ap"


class Tenant(BaseModel):
    id: UUID
    name: str
    slug: str
    domain: str | None = None
    tier_id: UUID
    data_region: DataRegion = DataRegion.us
    data_retention_days: int = 0
    status: TenantStatus = TenantStatus.active
    settings: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TenantCreate(BaseModel):
    name: str
    slug: str
    domain: str | None = None
    data_region: DataRegion = DataRegion.us
