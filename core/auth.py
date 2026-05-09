from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel


@dataclass
class AuthContext:
    """Current request authentication context."""
    tenant_id: UUID
    user_id: UUID | None = None
    api_key_id: UUID | None = None
    scopes: list[str] | None = None
    is_service_role: bool = False

    def has_scope(self, scope: str) -> bool:
        if self.is_service_role:
            return True
        if self.scopes is None:
            return True  # User auth has all scopes
        return scope in self.scopes or "admin" in self.scopes

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail=f"Missing required scope: {scope}"
            )


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    sub: str  # user_id or api_key_id
    tenant_id: str
    type: str = "user"  # "user" or "api_key"
    scopes: list[str] | None = None
    exp: int
