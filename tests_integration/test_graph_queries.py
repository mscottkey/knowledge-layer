"""Every query in graph/queries.py, run against a real Neo4j."""
import pytest

from graph import queries
from graph.schema import ensure_schema
from models.articles import ArticleStatus
from tests_integration.helpers import cypher, make_article, make_entity, make_signal


async def test_schema_creation_is_repeatable(tenant):
    await ensure_schema()
    await ensure_schema()


async def test_entity_merge_returns_the_same_node_for_the_same_name(tenant):
    first = await make_entity(tenant, "Dashboard")
    second = await make_entity(tenant, "Dashboard")
    other = await make_entity(tenant, "Billing")
    assert first == second
    assert other != first


async def test_find_articles_for_entity_returns_only_published(tenant):
    entity = await make_entity(tenant, "Dashboard")
    published = await make_article(tenant, "Live", status=ArticleStatus.published)
    pending = await make_article(tenant, "Draft", status=ArticleStatus.pending_review)
    for article in (published, pending):
        await queries.link_article_to_entity(article, entity, tenant)

    found = await queries.find_articles_for_entity(tenant, "Dashboard")
    assert [a["id"] for a in found] == [published]


async def test_article_roundtrip_and_batch_fetch(tenant):
    a = await make_article(tenant, "One", "first body")
    b = await make_article(tenant, "Two", "second body")
    one = await queries.get_article_by_id(a, tenant)
    assert one["title"] == "One" and one["body"] == "first body" and one["tenant_id"] == tenant
    many = await queries.get_articles_by_ids([a, b], tenant)
    assert {x["id"] for x in many} == {a, b}


async def test_one_tenant_cannot_see_another_tenants_graph(tenant):
    from uuid import uuid4

    other = str(uuid4())
    entity = await make_entity(tenant, "Dashboard")
    article = await make_article(tenant)
    await queries.link_article_to_entity(article, entity, tenant)

    assert await queries.get_article_by_id(article, other) is None
    assert await queries.get_articles_by_ids([article], other) == []
    assert await queries.find_articles_for_entity(other, "Dashboard") == []
    assert await queries.get_pending_review_articles(other) == []
    with pytest.raises(LookupError):
        await queries.create_review_event_node(other, article, "reviewer", "approved")


async def test_signal_counts_only_recent_distinct_signals_for_the_entity(tenant):
    entity = await make_entity(tenant, "Dashboard")
    article = await make_article(tenant)
    await queries.link_article_to_entity(article, entity, tenant)
    await make_signal(tenant, article, days_ago=1)
    await make_signal(tenant, article, days_ago=5)
    await make_signal(tenant, article, days_ago=45)
    assert await queries.get_signal_count_for_entity(tenant, "Dashboard", days=30) == 2
    assert await queries.get_signal_count_for_entity(tenant, "Unknown", days=30) == 0


async def test_coverage_gaps_list_entities_without_a_published_article(tenant):
    covered = await make_entity(tenant, "Covered")
    uncovered = await make_entity(tenant, "Uncovered")
    published = await make_article(tenant)
    await queries.link_article_to_entity(published, covered, tenant)
    gaps = await queries.find_coverage_gaps(tenant)
    assert [g["id"] for g in gaps] == [uncovered]


async def test_stale_articles_are_published_ones_not_touched_for_a_month(tenant):
    fresh = await make_article(tenant, "Fresh")
    old = await make_article(tenant, "Old")
    await cypher(tenant, "MATCH (a:Article {id: $id, tenant_id: $tenant_id}) SET a.updated_at = '2020-01-01T00:00:00+00:00'", id=old)
    stale = await queries.find_stale_articles(tenant, days_stale=30)
    assert [a["id"] for a in stale] == [old]
    assert fresh not in [a["id"] for a in stale]


async def test_status_update_and_pending_queue(tenant):
    article = await make_article(tenant, status=ArticleStatus.pending_review)
    assert [a["id"] for a in await queries.get_pending_review_articles(tenant)] == [article]
    await queries.update_article_status(article, "published", tenant)
    assert await queries.get_pending_review_articles(tenant) == []
    assert (await queries.get_article_by_id(article, tenant))["status"] == "published"


async def test_review_event_is_stored_and_linked_to_its_article(tenant):
    article = await make_article(tenant, status=ArticleStatus.pending_review)
    event_id = await queries.create_review_event_node(tenant, article, "reviewer-1", "approved", note="looks right")
    rows = await cypher(
        tenant,
        "MATCH (r:ReviewEvent {id: $id, tenant_id: $tenant_id})-[:REVIEWS]->(a:Article {tenant_id: $tenant_id}) "
        "RETURN a.id AS article, r.reviewer_id AS reviewer, r.action AS action, r.note AS note",
        id=event_id,
    )
    assert rows == [{"article": article, "reviewer": "reviewer-1", "action": "approved", "note": "looks right"}]


async def test_a_review_event_for_a_missing_article_fails_loudly(tenant):
    with pytest.raises(LookupError):
        await queries.create_review_event_node(tenant, "does-not-exist", "reviewer-1", "approved")


async def test_prior_approval_looks_back_along_the_version_chain_not_forward(tenant):
    old = await make_article(tenant, "v1", version=1)
    new = await make_article(tenant, "v2", version=2, status=ArticleStatus.pending_review)
    await queries.link_supersedes(new, old, "changed", tenant)

    assert await queries.has_prior_approval(old, tenant) is False
    await queries.create_review_event_node(tenant, old, "reviewer-1", "approved")
    assert await queries.has_prior_approval(old, tenant) is True
    # The newer version inherits the history of the one it replaces.
    assert await queries.has_prior_approval(new, tenant) is True

    # Approving only the newer version says nothing about the older one.
    other_old = await make_article(tenant, "o1")
    other_new = await make_article(tenant, "o2", version=2, status=ArticleStatus.pending_review)
    await queries.link_supersedes(other_new, other_old, "changed", tenant)
    await queries.create_review_event_node(tenant, other_new, "reviewer-1", "approved")
    assert await queries.has_prior_approval(other_old, tenant) is False
