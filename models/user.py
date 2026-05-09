from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserStatus(str, Enum):
    invited = "invited"
    active = "active"
    suspended = "suspended"
    locked = "locked"
    deleted = "deleted"


class UserRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class User(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    auth_user_id: UUID | None = None
    mfa_enabled: bool = False
    status: UserStatus = UserStatus.invited
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserProfile(BaseModel):
    user_id: UUID
    tenant_id: UUID
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    timezone: str = "UTC"
    locale: str = "en"
    privacy_consent_at: datetime | None = None
    marketing_consent: bool = False


class UserWithProfile(User):
    profile: UserProfile | None = None
    roles: list[str] = Field(default_factory=list)


class UserCreate(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role: UserRole = UserRole.member
