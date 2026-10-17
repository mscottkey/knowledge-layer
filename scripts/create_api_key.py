"""
Create an API key for a tenant, creating the tenant first if it does not exist.

    python -m scripts.create_api_key --tenant acme --name "support bot" --scopes read write
    python -m scripts.create_api_key --tenant <uuid> --name "reviewer console" --scopes review

The key is printed once. Only its hash is stored.
"""
import argparse
import asyncio
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from core.auth import VALID_SCOPES, create_api_key
from core.supabase import close_supabase_pool, get_supabase_pool


async def resolve_tenant(tenant: str) -> UUID:
    """Accept a tenant UUID, or a slug, which is looked up or created."""
    try:
        return UUID(tenant)
    except ValueError:
        pass

    slug = re.sub(r"[^a-z0-9-]+", "-", tenant.lower()).strip("-")
    pool = await get_supabase_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM tenants WHERE slug = $1", slug)
        if row:
            return row["id"]
        tenant_id = uuid4()
        await conn.execute("INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)", tenant_id, tenant, slug)
        return tenant_id


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True, help="tenant UUID, or a name/slug to look up or create")
    parser.add_argument("--name", required=True, help="what the key is for, shown in audit logs")
    parser.add_argument("--scopes", nargs="+", default=["read"], choices=sorted(VALID_SCOPES))
    parser.add_argument("--expires-in-days", type=int, help="expire the key after this many days")
    args = parser.parse_args()

    expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_in_days) if args.expires_in_days else None
    try:
        tenant_id = await resolve_tenant(args.tenant)
        created = await create_api_key(tenant_id, args.name, args.scopes, expires_at=expires_at)
    finally:
        await close_supabase_pool()

    print(f"tenant: {tenant_id}")
    print(f"scopes: {', '.join(args.scopes)}")
    print(f"key:    {created.key}")
    print("Store the key now. It cannot be shown again.")


if __name__ == "__main__":
    asyncio.run(main())
