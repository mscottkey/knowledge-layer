from typing import Any

import asyncpg

from core.config import get_settings
from core.logging import get_logger

logger = get_logger("core.supabase")

_pool: asyncpg.Pool | None = None


class MockSupabasePool:
    """Mock pool for testing without Supabase."""

    def __init__(self) -> None:
        self.tenants: dict[str, dict] = {}
        self.users: dict[str, dict] = {}
        self.api_keys: dict[str, dict] = {}
        self.audit_logs: list[dict] = []
        self.ai_usage_logs: list[dict] = []

    async def close(self) -> None:
        pass


_mock_pool: MockSupabasePool | None = None


async def get_supabase_pool() -> asyncpg.Pool | MockSupabasePool:
    global _pool, _mock_pool
    settings = get_settings()

    if settings.use_mocks:
        if _mock_pool is None:
            logger.info("Using mock Supabase pool")
            _mock_pool = MockSupabasePool()
        return _mock_pool

    if _pool is None:
        logger.info("Connecting to Supabase")
        _pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_supabase_pool() -> None:
    global _pool, _mock_pool
    if _pool is not None:
        await _pool.close()
        _pool = None
    _mock_pool = None


def get_mock_pool() -> MockSupabasePool | None:
    return _mock_pool


async def execute_query(
    query: str,
    *args: Any,
    fetch_one: bool = False,
    fetch_all: bool = False,
) -> Any:
    """Execute a query against Supabase."""
    settings = get_settings()

    if settings.use_mocks:
        return None

    pool = await get_supabase_pool()

    async with pool.acquire() as conn:
        if fetch_one:
            return await conn.fetchrow(query, *args)
        elif fetch_all:
            return await conn.fetch(query, *args)
        else:
            return await conn.execute(query, *args)
