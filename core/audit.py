from typing import Any
from uuid import UUID

from core.supabase import get_supabase_pool, get_mock_pool
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("core.audit")


async def log_audit(
    tenant_id: UUID,
    action: str,
    actor_id: UUID | None = None,
    actor_type: str = "user",
    api_key_id: UUID | None = None,
    table_name: str | None = None,
    record_id: str | None = None,
    status: str = "success",
    old_values: dict | None = None,
    new_values: dict | None = None,
    failure_reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    contains_pii: bool = False,
) -> UUID | None:
    """Log an audit event to Supabase."""
    settings = get_settings()

    if settings.use_mocks:
        mock_pool = get_mock_pool()
        if mock_pool:
            from uuid import uuid4
            event_id = uuid4()
            mock_pool.audit_logs.append({
                "id": str(event_id),
                "tenant_id": str(tenant_id),
                "actor_id": str(actor_id) if actor_id else None,
                "action": action,
                "status": status,
            })
            return event_id
        return None

    pool = await get_supabase_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO audit_logs (
                tenant_id, actor_id, actor_type, api_key_id,
                action, table_name, record_id, status,
                old_values, new_values, failure_reason,
                ip_address, user_agent, request_id, contains_pii
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING id
            """,
            tenant_id,
            actor_id,
            actor_type,
            api_key_id,
            action,
            table_name,
            record_id,
            status,
            old_values,
            new_values,
            failure_reason,
            ip_address,
            user_agent,
            request_id,
            contains_pii,
        )
        return row["id"] if row else None


async def log_security_event(
    tenant_id: UUID | None,
    event_type: str,
    severity: str,
    description: str,
    user_id: UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
    auto_action: str | None = None,
) -> UUID | None:
    """Log a security event to Supabase."""
    settings = get_settings()

    if settings.use_mocks:
        logger.warning(
            f"Security event: {event_type}",
            extra={"severity": severity, "description": description}
        )
        return None

    pool = await get_supabase_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO security_events (
                tenant_id, user_id, event_type, severity, description,
                ip_address, user_agent, metadata, auto_action
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            tenant_id,
            user_id,
            event_type,
            severity,
            description,
            ip_address,
            user_agent,
            metadata or {},
            auto_action,
        )
        return row["id"] if row else None
