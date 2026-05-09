from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from api.routers import health, ingest, serve, review
from graph.client import get_driver, close_driver
from graph.schema import ensure_schema
from vector.client import get_pool, close_pool, ensure_vector_table
from core.logging import setup_logging, get_logger
from core.config import get_settings

logger = get_logger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    settings = get_settings()

    logger.info(
        "Starting KnowledgeLayer API",
        extra={"environment": settings.ENVIRONMENT},
    )

    await get_driver()
    await ensure_schema()

    await get_pool()
    await ensure_vector_table()

    logger.info("All connections established")

    yield

    logger.info("Shutting down KnowledgeLayer API")
    await close_driver()
    await close_pool()


app = FastAPI(
    title="KnowledgeLayer",
    description="AI-native knowledge graph platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(serve.router)
app.include_router(review.router)
