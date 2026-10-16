from datetime import datetime, timedelta, timezone

from graph import queries
from graph.client import execute_query
from models.articles import Article, ArticleStatus
from models.entities import Entity, EntityType
from models.signals import KnowledgeSignal, SourceType


async def make_article(
    tenant_id: str,
    title: str = "Article",
    body: str = "Body",
    version: int = 1,
    status: ArticleStatus = ArticleStatus.published,
    confidence: float = 0.9,
) -> str:
    article = Article(tenant_id=tenant_id, title=title, body=body, version=version, status=status, confidence=confidence)
    return await queries.create_article_node(article)


async def make_entity(tenant_id: str, name: str = "Dashboard") -> str:
    return await queries.create_entity_node(Entity(tenant_id=tenant_id, name=name, type=EntityType.feature))


async def make_signal(tenant_id: str, article_id: str, days_ago: int = 0, text: str = "signal text") -> str:
    signal = KnowledgeSignal(
        tenant_id=tenant_id,
        source=SourceType.doc,
        source_id="s",
        raw_text=text,
        authority=0.8,
        ingested_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    signal_id = await queries.create_signal_node(signal)
    await queries.link_signal_to_article(signal_id, article_id, 0.8, tenant_id)
    return signal_id


async def cypher(tenant_id: str, query: str, **params):
    """Run a read query directly, for assertions about what is really in the graph."""
    return await execute_query(query, {"tenant_id": tenant_id, **params}, tenant_id)
