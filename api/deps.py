from typing import Annotated, Callable
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query

from core.auth import AuthContext, authenticate_api_key
from core.config import Settings, get_settings
from core.supabase import get_supabase_pool
from graph.client import get_driver
from vector.client import get_pool


async def get_graph_client():
    return await get_driver()


async def get_vector_store():
    return await get_pool()


async def get_db_pool():
    return await get_supabase_pool()


def _parse_tenant(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant_id format. Must be a valid UUID.")


async def get_auth_context(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    tenant_id: str | None = Query(None),
) -> AuthContext:
    """
    Work out who is calling and for which tenant.

    With an API key, the tenant is the key's tenant. A tenant id in the request is only checked
    against it, never trusted, so a key cannot be pointed at another tenant's data.

    With no key, the request is refused when authentication is required (the default whenever
    real stores are in use). Only in development, with AUTH_REQUIRED=false or mocked stores, is
    a tenant accepted from the X-Tenant-ID header or the tenant_id query parameter.
    """
    settings = get_settings()
    claimed = x_tenant_id or tenant_id

    if x_api_key:
        auth = await authenticate_api_key(x_api_key)
        if auth is None:
            raise HTTPException(status_code=401, detail="Invalid, expired or revoked API key.")
        if claimed is not None and _parse_tenant(claimed) != auth.tenant_id:
            raise HTTPException(status_code=403, detail="This API key does not belong to that tenant.")
        return auth

    if settings.auth_required:
        raise HTTPException(status_code=401, detail="Missing API key. Send it in the X-API-Key header.")

    if not claimed:
        raise HTTPException(
            status_code=401,
            detail="Missing tenant. Provide an X-API-Key header, or X-Tenant-ID in development.",
        )
    return AuthContext(tenant_id=_parse_tenant(claimed))


def require_scope(scope: str) -> Callable[..., AuthContext]:
    """Dependency factory: authenticate, then require a scope."""

    async def check_scope(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        auth.require_scope(scope)
        return auth

    return check_scope


# Type aliases for dependency injection
SettingsDep = Annotated[Settings, Depends(get_settings)]
GraphClientDep = Annotated[object, Depends(get_graph_client)]
VectorStoreDep = Annotated[object, Depends(get_vector_store)]
DbPoolDep = Annotated[object, Depends(get_db_pool)]
AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
ReadAuth = Annotated[AuthContext, Depends(require_scope("read"))]
WriteAuth = Annotated[AuthContext, Depends(require_scope("write"))]
ReviewAuth = Annotated[AuthContext, Depends(require_scope("review"))]
