from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request

from core.config import Settings, get_settings
from core.auth import AuthContext
from core.supabase import get_supabase_pool
from graph.client import get_driver
from vector.client import get_pool


async def get_graph_client():
    return await get_driver()


async def get_vector_store():
    return await get_pool()


async def get_db_pool():
    return await get_supabase_pool()


async def get_auth_context(
    request: Request,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    tenant_id: str | None = Query(None),
) -> AuthContext:
    """
    Extract authentication context from request.

    Supports:
    - X-Tenant-ID header (for development/testing)
    - X-API-Key header (for programmatic access)
    - tenant_id query param (for development/testing)
    - JWT token (TODO: implement with Supabase Auth)
    """
    settings = get_settings()

    # For development/testing: accept tenant_id from header or query
    effective_tenant_id = x_tenant_id or tenant_id

    if not effective_tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Missing tenant_id. Provide X-Tenant-ID header or tenant_id query param.",
        )

    try:
        tenant_uuid = UUID(effective_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid tenant_id format. Must be a valid UUID.",
        )

    # TODO: Validate API key if provided
    # TODO: Validate JWT token from Authorization header
    # TODO: Check tenant exists and is active

    return AuthContext(
        tenant_id=tenant_uuid,
        user_id=None,  # TODO: Extract from JWT
        api_key_id=None,  # TODO: Extract from API key validation
        scopes=None,  # TODO: Extract from API key or JWT
        is_service_role=settings.use_mocks,  # In mock mode, allow all
    )


async def require_scope(scope: str):
    """Dependency factory for requiring specific scopes."""
    async def check_scope(auth: AuthContext = Depends(get_auth_context)):
        auth.require_scope(scope)
        return auth
    return check_scope


# Type aliases for dependency injection
SettingsDep = Annotated[Settings, Depends(get_settings)]
GraphClientDep = Annotated[object, Depends(get_graph_client)]
VectorStoreDep = Annotated[object, Depends(get_vector_store)]
DbPoolDep = Annotated[object, Depends(get_db_pool)]
AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
