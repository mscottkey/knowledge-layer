from graph.client import get_driver
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("graph.schema")

CONSTRAINTS = [
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX article_tenant IF NOT EXISTS FOR (a:Article) ON (a.tenant_id, a.status)",
    "CREATE INDEX entity_tenant IF NOT EXISTS FOR (e:Entity) ON (e.tenant_id, e.name)",
    "CREATE INDEX signal_tenant IF NOT EXISTS FOR (s:Signal) ON (s.tenant_id, s.ingested_at)",
]


async def ensure_schema() -> None:
    settings = get_settings()

    if settings.use_mocks:
        logger.info("Skipping schema creation for mock driver")
        return

    driver = await get_driver()

    async with driver.session() as session:
        for constraint in CONSTRAINTS:
            logger.info("Creating constraint", extra={"query": constraint})
            await session.run(constraint)

        for index in INDEXES:
            logger.info("Creating index", extra={"query": index})
            await session.run(index)

    logger.info("Schema creation complete")
