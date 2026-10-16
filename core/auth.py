import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException

from core.config import get_settings
from core.logging import get_logger
from core.supabase import get_mock_pool, get_supabase_pool
from models.api_key import APIKeyWithSecret

logger = get_logger("core.auth")

KEY_PREFIX = "kl_live_"

# read: retrieve context. write: ingest signals. review: act on the review queue. admin: everything.
VALID_SCOPES = {"read", "write", "review", "admin"}


@dataclass
class AuthContext:
    """Who is calling and for which tenant. The tenant always comes from the credential."""

    tenant_id: UUID
    user_id: UUID | None = None
    api_key_id: UUID | None = None
    # None means unrestricted. Only the development path, with authentication switched off, uses it.
    scopes: list[str] | None = None
    is_service_role: bool = False

    def has_scope(self, scope: str) -> bool:
        if self.is_service_role or self.scopes is None:
            return True
        return scope in self.scopes or "admin" in self.scopes

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")

    @property
    def actor(self) -> str:
        """A stable identity for audit trails: the user if known, else the key."""
        if self.user_id:
            return f"user:{self.user_id}"
        if self.api_key_id:
            return f"key:{self.api_key_id}"
        return "dev"


def hash_api_key(raw_key: str) -> str:
    """Keys are long random strings, so a plain SHA-256 is enough and allows lookup by hash."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def create_api_key(
    tenant_id: UUID,
    name: str,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    description: str | None = None,
) -> APIKeyWithSecret:
    """Create a key for a tenant. The plaintext is returned once and never stored."""
    scopes = scopes or ["read"]
    unknown = set(scopes) - VALID_SCOPES
    if unknown:
        raise ValueError(f"Unknown scopes: {', '.join(sorted(unknown))}")

    raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = raw_key[:12]
    key_hash = hash_api_key(raw_key)
    settings = get_settings()

    if settings.mock_stores:
        pool = await get_supabase_pool()
        key_id = uuid4()
        now = datetime.now(timezone.utc)
        pool.api_keys[key_hash] = {
            "id": key_id,
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
            "key_prefix": prefix,
            "scopes": scopes,
            "rate_limit_rpm": 1000,
            "last_used_at": None,
            "total_requests": 0,
            "expires_at": expires_at,
            "revoked_at": None,
            "created_at": now,
            "created_by": None,
        }
        row = pool.api_keys[key_hash]
    else:
        pool = await get_supabase_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO api_keys (tenant_id, name, description, key_prefix, key_hash, scopes, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, tenant_id, name, description, key_prefix, scopes, rate_limit_rpm,
                          last_used_at, total_requests, expires_at, revoked_at, created_at, created_by
                """,
                tenant_id,
                name,
                description,
                prefix,
                key_hash,
                scopes,
                expires_at,
            )
    return APIKeyWithSecret(**dict(row), key=raw_key)


async def revoke_api_key(key_id: UUID, tenant_id: UUID) -> bool:
    settings = get_settings()
    pool = await get_supabase_pool()

    if settings.mock_stores:
        for row in pool.api_keys.values():
            if row["id"] == key_id and row["tenant_id"] == tenant_id and row["revoked_at"] is None:
                row["revoked_at"] = datetime.now(timezone.utc)
                return True
        return False

    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET revoked_at = NOW() WHERE id = $1 AND tenant_id = $2 AND revoked_at IS NULL",
            key_id,
            tenant_id,
        )
    return result == "UPDATE 1"


async def authenticate_api_key(raw_key: str) -> AuthContext | None:
    """Return the caller for a valid, live key, or None."""
    if not raw_key.startswith(KEY_PREFIX):
        return None

    key_hash = hash_api_key(raw_key)
    settings = get_settings()
    pool = await get_supabase_pool()
    now = datetime.now(timezone.utc)

    if settings.mock_stores:
        row = pool.api_keys.get(key_hash)
        if not row or row["revoked_at"] is not None:
            return None
        if row["expires_at"] is not None and row["expires_at"] <= now:
            return None
        row["last_used_at"] = now
        row["total_requests"] += 1
    else:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE api_keys
                   SET last_used_at = NOW(), total_requests = total_requests + 1
                 WHERE key_hash = $1
                   AND revoked_at IS NULL
                   AND (expires_at IS NULL OR expires_at > NOW())
                RETURNING id, tenant_id, scopes
                """,
                key_hash,
            )
        if not row:
            return None

    return AuthContext(tenant_id=row["tenant_id"], api_key_id=row["id"], scopes=list(row["scopes"]))
