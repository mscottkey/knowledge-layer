import os
import pytest

os.environ["USE_MOCKS"] = "true"
os.environ["NEO4J_URI"] = "neo4j+s://test.databases.neo4j.io"
os.environ["NEO4J_USERNAME"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = "test"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = "test-key"
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["REDIS_URL"] = "redis://localhost:6379"


@pytest.fixture(autouse=True)
def reset_mocks():
    from graph.client import _mock_driver, get_mock_driver
    from vector.client import _mock_store, get_mock_store

    yield

    import graph.client
    import vector.client

    if graph.client._mock_driver:
        graph.client._mock_driver.articles.clear()
        graph.client._mock_driver.entities.clear()
        graph.client._mock_driver.signals.clear()
        graph.client._mock_driver.relationships.clear()

    if vector.client._mock_store:
        vector.client._mock_store.embeddings.clear()
