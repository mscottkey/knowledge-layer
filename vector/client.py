from typing import Any

import asyncpg

from core.config import get_settings
from core.logging import get_logger

logger = get_logger("vector.client")

_pool: asyncpg.Pool | None = None
_mock_store: "MockVectorStore | None" = None


class MockVectorStore:
    def __init__(self) -> None:
        self.embeddings: dict[str, dict[str, Any]] = {}


async def get_pool() -> asyncpg.Pool | MockVectorStore:
    global _pool, _mock_store
    settings = get_settings()

    if settings.use_mocks:
        if _mock_store is None:
            logger.info("Using mock vector store")
            _mock_store = MockVectorStore()
        return _mock_store

    if _pool is None:
        logger.info("Connecting to Supabase/pgvector")
        _pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool, _mock_store
    if _pool is not None:
        await _pool.close()
        _pool = None
    _mock_store = None


async def ensure_vector_table() -> None:
    """Verify the embeddings table exists. Table should be created via migrations."""
    settings = get_settings()

    if settings.use_mocks:
        logger.info("Skipping vector table check for mock store")
        return

    pool = await get_pool()

    async with pool.acquire() as conn:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'embeddings'
            );
        """)

        if not exists:
            logger.warning(
                "Embeddings table not found. Run migrations: "
                "supabase db push or apply supabase/migrations/*.sql"
            )
        else:
            logger.info("Vector table verified")


def get_mock_store() -> MockVectorStore | None:
    return _mock_store
