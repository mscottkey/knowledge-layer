import os

import pytest
import pytest_asyncio

os.environ["USE_MOCKS"] = "true"
os.environ["NEO4J_URI"] = "neo4j+s://test.databases.neo4j.io"
os.environ["NEO4J_USERNAME"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = "test"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = "test-key"
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["REDIS_URL"] = "redis://localhost:6379"

TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
OTHER_TENANT_ID = "87654321-4321-8765-4321-876543218765"


@pytest_asyncio.fixture(autouse=True)
async def mock_stores():
    """
    Start every test with empty, initialised mock stores. The app does the initialising in its
    lifespan, which the test client does not run. Without it the mock vector store silently
    drops writes and retrieval tests pass on empty results.
    """
    from core.supabase import close_supabase_pool, get_supabase_pool
    from graph.client import close_driver, get_driver
    from vector.client import close_pool, get_pool
    from worker import queue

    await close_driver()
    await close_pool()
    await close_supabase_pool()
    queue.reset_mock_queue()
    await get_driver()
    await get_pool()
    await get_supabase_pool()
    yield


@pytest.fixture
def settings():
    """The shared settings object. Changes made in a test are undone afterwards."""
    from core.config import get_settings

    s = get_settings()
    saved = s.model_copy()
    yield s
    for name in type(s).model_fields:
        setattr(s, name, getattr(saved, name))


@pytest.fixture
def require_auth(settings):
    """Turn on API-key enforcement, as it is in production."""
    settings.AUTH_REQUIRED = True
    return settings


@pytest.fixture
def low_threshold(settings):
    """Auto-publish everything."""
    settings.CONFIDENCE_THRESHOLD = 0.0
    return settings
