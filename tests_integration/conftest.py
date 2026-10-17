"""
Integration tests: real Neo4j and real Postgres with pgvector, fake embeddings and synthesis.

Run them with the services up and these set:

    NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=...
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
    pytest tests_integration

The Postgres database must have supabase/migrations applied. Without these variables
every test here is skipped, so the normal `pytest` run stays offline and fast.
"""
import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

os.environ.setdefault("MOCK_MODELS", "true")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")

REQUIRED = ("NEO4J_URI", "DATABASE_URL")


def pytest_collection_modifyitems(config, items):
    missing = [name for name in REQUIRED if not os.getenv(name)]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"integration tests need {', '.join(missing)}")
    for item in items:
        item.add_marker(skip)


@pytest_asyncio.fixture(autouse=True)
async def close_connections():
    """Each test gets fresh connections, because pools are tied to the test's event loop."""
    yield
    from core.supabase import close_supabase_pool
    from graph.client import close_driver
    from vector.client import close_pool

    await close_driver()
    await close_pool()
    await close_supabase_pool()


@pytest_asyncio.fixture
async def tenant():
    """A fresh tenant row in Postgres. Its Neo4j nodes and rows are removed afterwards."""
    from core.supabase import get_supabase_pool
    from graph.client import get_driver

    tenant_id = str(uuid4())
    pool = await get_supabase_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)",
            UUID(tenant_id),
            f"test-{tenant_id[:8]}",
            f"test-{tenant_id}",
        )
    yield tenant_id
    driver = await get_driver()
    async with driver.session() as session:
        await session.run("MATCH (n {tenant_id: $t}) DETACH DELETE n", t=tenant_id)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM audit_logs WHERE tenant_id = $1", UUID(tenant_id))
        await conn.execute("DELETE FROM api_keys WHERE tenant_id = $1", UUID(tenant_id))
        await conn.execute("DELETE FROM tenants WHERE id = $1", UUID(tenant_id))


@pytest.fixture
def threshold():
    """Set the auto-publish confidence threshold for one test, then restore it."""
    from core.config import get_settings

    settings = get_settings()
    original = settings.CONFIDENCE_THRESHOLD

    def set_to(value: float) -> None:
        settings.CONFIDENCE_THRESHOLD = value

    yield set_to
    settings.CONFIDENCE_THRESHOLD = original


@pytest_asyncio.fixture
async def api_key(tenant):
    """A real API key, stored hashed in Postgres, with every scope but admin."""
    from core.auth import create_api_key

    created = await create_api_key(UUID(tenant), "integration test", ["read", "write", "review"])
    return created.key


@pytest_asyncio.fixture
async def client(tenant, api_key):
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"X-API-Key": api_key}) as c:
        yield c
