from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from core.config import get_settings
from core.logging import get_logger

logger = get_logger("graph.client")

_driver: AsyncDriver | None = None
_mock_driver: "MockNeo4jDriver | None" = None


class MockNeo4jDriver:
    def __init__(self) -> None:
        self.articles: dict[str, dict] = {}
        self.entities: dict[str, dict] = {}
        self.signals: dict[str, dict] = {}
        self.relationships: list[dict] = []

    async def close(self) -> None:
        pass


class MockSession:
    def __init__(self, driver: MockNeo4jDriver) -> None:
        self.driver = driver

    async def __aenter__(self) -> "MockSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def run(self, query: str, **params: Any) -> "MockResult":
        return MockResult([])


class MockResult:
    def __init__(self, data: list[dict]) -> None:
        self._data = data

    async def data(self) -> list[dict]:
        return self._data

    async def single(self) -> dict | None:
        return self._data[0] if self._data else None


async def get_driver() -> AsyncDriver | MockNeo4jDriver:
    global _driver, _mock_driver
    settings = get_settings()

    if settings.mock_stores:
        if _mock_driver is None:
            logger.info("Using mock Neo4j driver")
            _mock_driver = MockNeo4jDriver()
        return _mock_driver

    if _driver is None:
        logger.info("Connecting to Neo4j", extra={"uri": settings.NEO4J_URI})
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
    return _driver


async def close_driver() -> None:
    global _driver, _mock_driver
    if _driver is not None:
        await _driver.close()
        _driver = None
    if _mock_driver is not None:
        await _mock_driver.close()
        _mock_driver = None


async def execute_query(
    query: str,
    params: dict[str, Any],
    tenant_id: str,
) -> list[dict[str, Any]]:
    if "tenant_id" not in params:
        params["tenant_id"] = tenant_id

    assert params.get("tenant_id") == tenant_id, "tenant_id mismatch in query params"

    driver = await get_driver()
    settings = get_settings()

    if settings.mock_stores:
        return await _execute_mock_query(driver, query, params)

    async with driver.session() as session:
        result = await session.run(query, **params)
        return await result.data()


async def _execute_mock_query(
    driver: MockNeo4jDriver,
    query: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    tenant_id = params.get("tenant_id", "")
    query_lower = query.lower()

    if "create" in query_lower and ":article" in query_lower:
        article_id = params.get("id", "")
        driver.articles[article_id] = params
        return [{"id": article_id}]

    if "create" in query_lower and ":entity" in query_lower:
        entity_id = params.get("id", "")
        driver.entities[entity_id] = params
        return [{"id": entity_id}]

    if "create" in query_lower and ":signal" in query_lower:
        signal_id = params.get("id", "")
        driver.signals[signal_id] = params
        return [{"id": signal_id}]

    if "match" in query_lower and ":article" in query_lower:
        results = []
        for article in driver.articles.values():
            if article.get("tenant_id") == tenant_id:
                if "status" in params and article.get("status") != params["status"]:
                    continue
                if "entity_name" in params:
                    entity_ids = article.get("entity_ids", [])
                    entity_names = [
                        driver.entities.get(eid, {}).get("name", "")
                        for eid in entity_ids
                    ]
                    if params["entity_name"] not in entity_names:
                        continue
                results.append(article)
        return results

    if "match" in query_lower and ":entity" in query_lower:
        results = []
        for entity in driver.entities.values():
            if entity.get("tenant_id") == tenant_id:
                results.append(entity)
        return results

    return []


def get_mock_driver() -> MockNeo4jDriver | None:
    return _mock_driver
