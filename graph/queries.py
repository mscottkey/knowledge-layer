from datetime import datetime, timezone
from typing import Any, Sequence

from graph.client import execute_query, get_mock_driver
from models.articles import Article
from models.entities import Entity
from models.signals import KnowledgeSignal
from core.config import get_settings


async def find_articles_for_entity(tenant_id: str, entity_name: str) -> list[dict[str, Any]]:
    query = """
    MATCH (e:Entity {tenant_id: $tenant_id, name: $entity_name})<-[:COVERS]-(a:Article {tenant_id: $tenant_id})
    WHERE a.status = 'published'
    RETURN a.id AS id, a.title AS title, a.body AS body, a.version AS version,
           a.confidence AS confidence, a.status AS status
    """
    return await execute_query(
        query,
        {"tenant_id": tenant_id, "entity_name": entity_name},
        tenant_id,
    )


async def create_article_node(article: Article) -> str:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            driver.articles[str(article.id)] = article.to_neo4j_props()
        return str(article.id)

    query = """
    CREATE (a:Article {
        id: $id,
        tenant_id: $tenant_id,
        title: $title,
        body: $body,
        version: $version,
        status: $status,
        confidence: $confidence,
        entity_ids: $entity_ids,
        created_at: $created_at,
        updated_at: $updated_at
    })
    RETURN a.id AS id
    """
    props = article.to_neo4j_props()
    result = await execute_query(query, props, article.tenant_id)
    return result[0]["id"] if result else str(article.id)


async def link_supersedes(new_id: str, old_id: str, diff_summary: str, tenant_id: str) -> None:
    """Record that `new_id` is a newer version of `old_id`. Does not change either article's status."""
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            driver.relationships.append({
                "type": "SUPERSEDES",
                "from": new_id,
                "to": old_id,
                "diff_summary": diff_summary,
            })
        return

    query = """
    MATCH (old:Article {id: $old_id, tenant_id: $tenant_id})
    MATCH (new:Article {id: $new_id, tenant_id: $tenant_id})
    MERGE (new)-[r:SUPERSEDES]->(old)
    SET r.diff_summary = $diff_summary
    """
    await execute_query(
        query,
        {"old_id": old_id, "new_id": new_id, "diff_summary": diff_summary, "tenant_id": tenant_id},
        tenant_id,
    )


async def supersede_replaced_versions(article_id: str, tenant_id: str) -> list[str]:
    """
    Retire every older version that `article_id` replaces. Call this when the new version is
    published, so the knowledge base never has a gap while a replacement waits for review.
    Returns the ids that were retired.
    """
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        retired: list[str] = []
        if driver:
            frontier = [article_id]
            seen: set[str] = set()
            while frontier:
                current = frontier.pop()
                for rel in driver.relationships:
                    if rel["type"] == "SUPERSEDES" and rel["from"] == current and rel["to"] not in seen:
                        seen.add(rel["to"])
                        frontier.append(rel["to"])
                        old = driver.articles.get(rel["to"])
                        if old and old.get("tenant_id") == tenant_id and old.get("status") in ("published", "pending_review"):
                            old["status"] = "superseded"
                            retired.append(rel["to"])
        return retired

    query = """
    MATCH (new:Article {id: $article_id, tenant_id: $tenant_id})-[:SUPERSEDES*1..]->(old:Article {tenant_id: $tenant_id})
    WHERE old.status IN ['published', 'pending_review']
    WITH DISTINCT old
    SET old.status = 'superseded', old.updated_at = $now
    RETURN old.id AS id
    """
    rows = await execute_query(
        query,
        {"article_id": article_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc).isoformat()},
        tenant_id,
    )
    return [r["id"] for r in rows]


async def supersede_article(old_id: str, new_id: str, diff_summary: str, tenant_id: str) -> None:
    """Link the versions and retire the old one immediately. Prefer link_supersedes plus publish."""
    await link_supersedes(new_id, old_id, diff_summary, tenant_id)
    await supersede_replaced_versions(new_id, tenant_id)


async def copy_entity_links(from_article_id: str, to_article_id: str, tenant_id: str) -> None:
    """Make `to_article_id` cover the same entities as `from_article_id`."""
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            for rel in list(driver.relationships):
                if rel["type"] == "COVERS" and rel["from"] == from_article_id:
                    driver.relationships.append({"type": "COVERS", "from": to_article_id, "to": rel["to"]})
            source = driver.articles.get(from_article_id)
            target = driver.articles.get(to_article_id)
            if source and target:
                target["entity_ids"] = list(source.get("entity_ids", []))
        return

    query = """
    MATCH (src:Article {id: $from_id, tenant_id: $tenant_id})-[:COVERS]->(e:Entity {tenant_id: $tenant_id})
    MATCH (dst:Article {id: $to_id, tenant_id: $tenant_id})
    MERGE (dst)-[:COVERS]->(e)
    """
    await execute_query(
        query,
        {"from_id": from_article_id, "to_id": to_article_id, "tenant_id": tenant_id},
        tenant_id,
    )


async def get_article_history(article_id: str, tenant_id: str) -> list[dict[str, Any]]:
    query = """
    MATCH (a:Article {id: $article_id, tenant_id: $tenant_id})
    OPTIONAL MATCH path = (a)-[:SUPERSEDES*]->(prev:Article)
    WITH a, prev, path
    ORDER BY prev.version DESC
    RETURN a.id AS id, a.title AS title, a.version AS version, a.status AS status,
           collect({id: prev.id, version: prev.version, status: prev.status}) AS history
    """
    return await execute_query(
        query,
        {"article_id": article_id, "tenant_id": tenant_id},
        tenant_id,
    )


async def find_stale_articles(tenant_id: str, days_stale: int = 30) -> list[dict[str, Any]]:
    query = """
    MATCH (a:Article {tenant_id: $tenant_id, status: 'published'})
    WHERE datetime(a.updated_at) < datetime() - duration({days: $days_stale})
    RETURN a.id AS id, a.title AS title, a.updated_at AS updated_at, a.confidence AS confidence
    ORDER BY a.updated_at ASC
    """
    return await execute_query(
        query,
        {"tenant_id": tenant_id, "days_stale": days_stale},
        tenant_id,
    )


async def find_coverage_gaps(tenant_id: str) -> list[dict[str, Any]]:
    query = """
    MATCH (e:Entity {tenant_id: $tenant_id})
    WHERE NOT EXISTS {
        MATCH (e)<-[:COVERS]-(a:Article {status: 'published', tenant_id: $tenant_id})
    }
    RETURN e.id AS id, e.name AS name, e.type AS type
    """
    return await execute_query(
        query,
        {"tenant_id": tenant_id},
        tenant_id,
    )


async def create_entity_node(entity: Entity) -> str:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            driver.entities[str(entity.id)] = entity.to_neo4j_props()
        return str(entity.id)

    query = """
    MERGE (e:Entity {tenant_id: $tenant_id, name: $name})
    ON CREATE SET e.id = $id, e.type = $type, e.canonical = $canonical
    ON MATCH SET e.type = $type
    RETURN e.id AS id
    """
    props = entity.to_neo4j_props()
    result = await execute_query(query, props, entity.tenant_id)
    return result[0]["id"] if result else str(entity.id)


async def link_article_to_entity(article_id: str, entity_id: str, tenant_id: str) -> None:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            driver.relationships.append({
                "type": "COVERS",
                "from": article_id,
                "to": entity_id,
            })
            if article_id in driver.articles:
                entity_ids = driver.articles[article_id].get("entity_ids", [])
                if entity_id not in entity_ids:
                    entity_ids.append(entity_id)
                    driver.articles[article_id]["entity_ids"] = entity_ids
        return

    query = """
    MATCH (a:Article {id: $article_id, tenant_id: $tenant_id})
    MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})
    MERGE (a)-[:COVERS]->(e)
    """
    await execute_query(
        query,
        {"article_id": article_id, "entity_id": entity_id, "tenant_id": tenant_id},
        tenant_id,
    )


async def link_signal_to_article(signal_id: str, article_id: str, weight: float, tenant_id: str) -> None:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            driver.relationships.append({
                "type": "CONTRIBUTED_TO",
                "from": signal_id,
                "to": article_id,
                "weight": weight,
            })
        return

    query = """
    MATCH (s:Signal {id: $signal_id, tenant_id: $tenant_id})
    MATCH (a:Article {id: $article_id, tenant_id: $tenant_id})
    MERGE (s)-[:CONTRIBUTED_TO {weight: $weight}]->(a)
    """
    await execute_query(
        query,
        {"signal_id": signal_id, "article_id": article_id, "weight": weight, "tenant_id": tenant_id},
        tenant_id,
    )


async def create_signal_node(signal: KnowledgeSignal) -> str:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            driver.signals[str(signal.id)] = {
                "id": str(signal.id),
                "tenant_id": signal.tenant_id,
                "source": signal.source.value,
                "source_id": signal.source_id,
                "raw_text": signal.raw_text,
                "authority": signal.authority,
                "ingested_at": signal.ingested_at.isoformat(),
            }
        return str(signal.id)

    query = """
    CREATE (s:Signal {
        id: $id,
        tenant_id: $tenant_id,
        source: $source,
        source_id: $source_id,
        raw_text: $raw_text,
        authority: $authority,
        ingested_at: $ingested_at
    })
    RETURN s.id AS id
    """
    params = {
        "id": str(signal.id),
        "tenant_id": signal.tenant_id,
        "source": signal.source.value,
        "source_id": signal.source_id,
        "raw_text": signal.raw_text,
        "authority": signal.authority,
        "ingested_at": signal.ingested_at.isoformat(),
    }
    result = await execute_query(query, params, signal.tenant_id)
    return result[0]["id"] if result else str(signal.id)


async def get_signal_count_for_entity(tenant_id: str, entity_name: str, days: int = 30) -> int:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            return len(driver.signals)
        return 0

    query = """
    MATCH (s:Signal {tenant_id: $tenant_id})-[:CONTRIBUTED_TO]->(a:Article)-[:COVERS]->(e:Entity {name: $entity_name, tenant_id: $tenant_id})
    WHERE datetime(s.ingested_at) > datetime() - duration({days: $days})
    RETURN count(DISTINCT s) AS count
    """
    result = await execute_query(
        query,
        {"tenant_id": tenant_id, "entity_name": entity_name, "days": days},
        tenant_id,
    )
    return result[0]["count"] if result else 0


async def get_article_by_id(article_id: str, tenant_id: str) -> dict[str, Any] | None:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver and article_id in driver.articles:
            article = driver.articles[article_id]
            if article.get("tenant_id") == tenant_id:
                return article
        return None

    query = """
    MATCH (a:Article {id: $article_id, tenant_id: $tenant_id})
    RETURN a.id AS id, a.tenant_id AS tenant_id, a.title AS title, a.body AS body,
           a.version AS version, a.status AS status, a.confidence AS confidence,
           a.entity_ids AS entity_ids, a.created_at AS created_at, a.updated_at AS updated_at
    """
    result = await execute_query(
        query,
        {"article_id": article_id, "tenant_id": tenant_id},
        tenant_id,
    )
    return result[0] if result else None


async def get_articles_by_ids(
    article_ids: list[str],
    tenant_id: str,
    statuses: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch articles by id. Pass `statuses` to restrict the result, for example ["published"]."""
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            results = []
            for aid in article_ids:
                if aid in driver.articles:
                    article = driver.articles[aid]
                    if article.get("tenant_id") != tenant_id:
                        continue
                    if statuses is not None and article.get("status") not in statuses:
                        continue
                    results.append(article)
            return results
        return []

    query = """
    MATCH (a:Article)
    WHERE a.id IN $article_ids AND a.tenant_id = $tenant_id
      AND ($statuses IS NULL OR a.status IN $statuses)
    RETURN a.id AS id, a.tenant_id AS tenant_id, a.title AS title, a.body AS body,
           a.version AS version, a.status AS status, a.confidence AS confidence,
           a.entity_ids AS entity_ids, a.created_at AS created_at, a.updated_at AS updated_at
    """
    return await execute_query(
        query,
        {"article_ids": article_ids, "tenant_id": tenant_id, "statuses": list(statuses) if statuses is not None else None},
        tenant_id,
    )


async def get_pending_review_articles(tenant_id: str) -> list[dict[str, Any]]:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver:
            return [
                a for a in driver.articles.values()
                if a.get("tenant_id") == tenant_id and a.get("status") == "pending_review"
            ]
        return []

    query = """
    MATCH (a:Article {tenant_id: $tenant_id, status: 'pending_review'})
    RETURN a.id AS id, a.title AS title, a.body AS body, a.version AS version,
           a.confidence AS confidence, a.created_at AS created_at
    ORDER BY a.created_at ASC
    """
    return await execute_query(query, {"tenant_id": tenant_id}, tenant_id)


async def update_article_status(article_id: str, status: str, tenant_id: str) -> None:
    settings = get_settings()

    if settings.mock_stores:
        driver = get_mock_driver()
        if driver and article_id in driver.articles:
            driver.articles[article_id]["status"] = status
        return

    query = """
    MATCH (a:Article {id: $article_id, tenant_id: $tenant_id})
    SET a.status = $status, a.updated_at = $now
    """
    await execute_query(
        query,
        {"article_id": article_id, "status": status, "tenant_id": tenant_id, "now": datetime.now(timezone.utc).isoformat()},
        tenant_id,
    )


async def create_review_event_node(
    tenant_id: str,
    article_id: str,
    reviewer_id: str,
    action: str,
    edited_body: str | None = None,
    note: str | None = None,
) -> str:
    from uuid import uuid4

    event_id = str(uuid4())
    settings = get_settings()

    if settings.mock_stores:
        return event_id

    query = """
    MATCH (a:Article {id: $article_id, tenant_id: $tenant_id})
    CREATE (r:ReviewEvent {
        id: $id,
        tenant_id: $tenant_id,
        article_id: $article_id,
        reviewer_id: $reviewer_id,
        action: $action,
        edited_body: $edited_body,
        note: $note,
        created_at: $created_at
    })-[:REVIEWS]->(a)
    RETURN r.id AS id
    """
    result = await execute_query(
        query,
        {
            "id": event_id,
            "tenant_id": tenant_id,
            "article_id": article_id,
            "reviewer_id": reviewer_id,
            "action": action,
            "edited_body": edited_body,
            "note": note,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        tenant_id,
    )
    if not result:
        raise LookupError(f"Article {article_id} not found for tenant {tenant_id}")
    return result[0]["id"]


async def has_prior_approval(article_id: str, tenant_id: str) -> bool:
    settings = get_settings()

    if settings.mock_stores:
        return False

    query = """
    MATCH (a:Article {id: $article_id, tenant_id: $tenant_id})-[:SUPERSEDES*0..]->(prev:Article {tenant_id: $tenant_id})
    MATCH (r:ReviewEvent {action: 'approved', tenant_id: $tenant_id})-[:REVIEWS]->(prev)
    RETURN count(r) > 0 AS has_approval
    """
    result = await execute_query(
        query,
        {"article_id": article_id, "tenant_id": tenant_id},
        tenant_id,
    )
    return result[0]["has_approval"] if result else False
