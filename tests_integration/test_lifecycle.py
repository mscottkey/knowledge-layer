"""
The article lifecycle through the HTTP API, on real Neo4j and Postgres:
nothing unreviewed reaches agents, a replacement never takes the live article offline,
and a reviewer's edit is what gets published.
"""
from uuid import UUID

from core.supabase import get_supabase_pool
from tests_integration.helpers import cypher

ORIGINAL = "The Dashboard feature shows Analytics reports for every team"
CONFLICTING = "The Dashboard feature no longer shows Analytics reports after the latest release"


async def ingest(client, tenant: str, text: str, source_id: str) -> dict:
    r = await client.post(
        f"/ingest/process/{source_id}",
        json={"tenant_id": tenant, "source_id": source_id, "raw_text": text},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def served(client, tenant: str) -> list[dict]:
    r = await client.get("/context", params={"query": "Dashboard Analytics", "tenant_id": tenant, "limit": 10})
    assert r.status_code == 200, r.text
    return r.json()["results"]


async def approve(client, tenant: str, article_id: str):
    return await client.post(f"/review/{article_id}/approve", params={"tenant_id": tenant}, json={"reviewer_id": "reviewer-1"})


async def stored_embeddings(tenant: str) -> set[str]:
    pool = await get_supabase_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT article_id FROM embeddings WHERE tenant_id = $1", UUID(tenant))
    return {r["article_id"] for r in rows}


async def test_an_unreviewed_article_is_invisible_to_agents_until_approved(client, tenant, threshold):
    threshold(0.99)
    result = await ingest(client, tenant, ORIGINAL, "d1")
    assert result["status"] == "pending_review"

    assert await served(client, tenant) == []

    approved = await approve(client, tenant, result["article_id"])
    assert approved.status_code == 200, approved.text
    assert [a["article_id"] for a in await served(client, tenant)] == [result["article_id"]]


async def test_a_pending_replacement_leaves_the_live_article_in_place(client, tenant, threshold):
    threshold(0.0)
    live = await ingest(client, tenant, ORIGINAL, "d1")
    assert live["status"] == "published"

    threshold(0.99)
    replacement = await ingest(client, tenant, CONFLICTING, "d2")
    assert replacement["conflict_detected"] is True
    assert replacement["status"] == "pending_review"

    # While the replacement waits, agents still get the published version.
    assert [a["article_id"] for a in await served(client, tenant)] == [live["article_id"]]
    rows = await cypher(tenant, "MATCH (a:Article {id: $id, tenant_id: $tenant_id}) RETURN a.status AS status", id=live["article_id"])
    assert rows == [{"status": "published"}]


async def test_approving_a_replacement_swaps_it_in_and_retires_the_old_version(client, tenant, threshold):
    threshold(0.0)
    live = await ingest(client, tenant, ORIGINAL, "d1")
    threshold(0.99)
    replacement = await ingest(client, tenant, CONFLICTING, "d2")

    assert (await approve(client, tenant, replacement["article_id"])).status_code == 200

    served_now = await served(client, tenant)
    assert [a["article_id"] for a in served_now] == [replacement["article_id"]]
    assert served_now[0]["version"] == 2
    rows = await cypher(tenant, "MATCH (a:Article {id: $id, tenant_id: $tenant_id}) RETURN a.status AS status", id=live["article_id"])
    assert rows == [{"status": "superseded"}]
    assert live["article_id"] not in await stored_embeddings(tenant)


async def test_an_auto_published_replacement_retires_the_old_version_straight_away(client, tenant, threshold):
    threshold(0.0)
    live = await ingest(client, tenant, ORIGINAL, "d1")
    replacement = await ingest(client, tenant, CONFLICTING, "d2")
    assert replacement["status"] == "published"

    assert [a["article_id"] for a in await served(client, tenant)] == [replacement["article_id"]]
    rows = await cypher(tenant, "MATCH (a:Article {id: $id, tenant_id: $tenant_id}) RETURN a.status AS status", id=live["article_id"])
    assert rows == [{"status": "superseded"}]


async def test_rejecting_a_replacement_keeps_the_live_article(client, tenant, threshold):
    threshold(0.0)
    live = await ingest(client, tenant, ORIGINAL, "d1")
    threshold(0.99)
    replacement = await ingest(client, tenant, CONFLICTING, "d2")

    r = await client.post(
        f"/review/{replacement['article_id']}/reject", params={"tenant_id": tenant}, json={"reviewer_id": "reviewer-1", "note": "wrong"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft"
    assert [a["article_id"] for a in await served(client, tenant)] == [live["article_id"]]


async def test_an_edit_publishes_the_reviewers_text_as_a_new_version(client, tenant, threshold):
    threshold(0.0)
    live = await ingest(client, tenant, ORIGINAL, "d1")
    threshold(0.99)
    pending = await ingest(client, tenant, CONFLICTING, "d2")
    original_body = (await cypher(tenant, "MATCH (a:Article {id: $id, tenant_id: $tenant_id}) RETURN a.body AS body", id=pending["article_id"]))[0]["body"]

    edited_text = "Reviewer-written article body about the Dashboard"
    r = await client.post(
        f"/review/{pending['article_id']}/edit",
        params={"tenant_id": tenant},
        json={"reviewer_id": "reviewer-1", "edited_body": edited_text},
    )
    assert r.status_code == 200, r.text
    edit = r.json()
    assert edit["previous_article_id"] == pending["article_id"]
    assert edit["article_id"] != pending["article_id"]
    assert edit["status"] == "published"

    # Agents get exactly what the reviewer wrote.
    results = await served(client, tenant)
    assert [(a["article_id"], a["body"], a["version"]) for a in results] == [(edit["article_id"], edited_text, 3)]

    # The history is intact: the text that was edited is still on record, and nothing older stays live.
    statuses = await cypher(
        tenant, "MATCH (a:Article {tenant_id: $tenant_id}) RETURN a.id AS id, a.status AS status, a.body AS body"
    )
    by_id = {r["id"]: r for r in statuses}
    assert by_id[pending["article_id"]]["status"] == "superseded"
    assert by_id[pending["article_id"]]["body"] == original_body
    assert by_id[live["article_id"]]["status"] == "superseded"
    events = await cypher(
        tenant,
        "MATCH (r:ReviewEvent {tenant_id: $tenant_id})-[:REVIEWS]->(a:Article) RETURN r.action AS action, r.edited_body AS body, a.id AS article",
    )
    assert events == [{"action": "edited", "body": edited_text, "article": edit["article_id"]}]


async def test_an_edited_article_keeps_covering_the_same_entities(client, tenant, threshold):
    threshold(0.99)
    pending = await ingest(client, tenant, ORIGINAL, "d1")
    r = await client.post(
        f"/review/{pending['article_id']}/edit", params={"tenant_id": tenant}, json={"reviewer_id": "r", "edited_body": "Edited body"}
    )
    new_id = r.json()["article_id"]
    covered = await cypher(
        tenant,
        "MATCH (a:Article {id: $id, tenant_id: $tenant_id})-[:COVERS]->(e:Entity) RETURN e.name AS name ORDER BY name",
        id=new_id,
    )
    assert "Dashboard" in [c["name"] for c in covered]


async def test_retired_and_repeated_reviews_are_refused(client, tenant, threshold):
    threshold(0.99)
    first = await ingest(client, tenant, ORIGINAL, "d1")
    assert (await approve(client, tenant, first["article_id"])).status_code == 200

    # Approving twice is a conflict, not a second event.
    assert (await approve(client, tenant, first["article_id"])).status_code == 409

    # A retired version cannot be reviewed.
    threshold(0.99)
    replacement = await ingest(client, tenant, CONFLICTING, "d2")
    assert (await approve(client, tenant, replacement["article_id"])).status_code == 200
    assert (await approve(client, tenant, first["article_id"])).status_code == 409
    edit = await client.post(
        f"/review/{first['article_id']}/edit", params={"tenant_id": tenant}, json={"reviewer_id": "r", "edited_body": "x"}
    )
    assert edit.status_code == 409


async def test_entities_on_an_article_are_the_ids_the_graph_holds(client, tenant, threshold):
    threshold(0.0)
    await ingest(client, tenant, ORIGINAL, "d1")
    second = await ingest(client, tenant, CONFLICTING, "d2")
    rows = await cypher(
        tenant,
        "MATCH (a:Article {id: $id, tenant_id: $tenant_id}) UNWIND a.entity_ids AS eid "
        "OPTIONAL MATCH (e:Entity {id: eid, tenant_id: $tenant_id}) RETURN eid, e IS NOT NULL AS exists",
        id=second["article_id"],
    )
    assert rows and all(r["exists"] for r in rows)


async def test_the_review_queue_shows_the_version_being_replaced_and_its_sources(client, tenant, threshold):
    threshold(0.0)
    live = await ingest(client, tenant, ORIGINAL, "d1")
    threshold(0.99)
    replacement = await ingest(client, tenant, CONFLICTING, "d2")

    items = (await client.get("/review/queue")).json()["items"]
    assert [i["article_id"] for i in items] == [replacement["article_id"]]
    item = items[0]
    assert item["reason"] == "conflict"
    assert item["replaces"]["article_id"] == live["article_id"]
    assert item["replaces"]["body"]
    assert [s["source_id"] for s in item["sources"]] == ["d2"]
    assert "no longer shows" in item["sources"][0]["excerpt"]


async def test_a_new_low_confidence_article_has_sources_but_nothing_to_replace(client, tenant, threshold):
    threshold(0.99)
    await ingest(client, tenant, ORIGINAL, "d1")

    item = (await client.get("/review/queue")).json()["items"][0]
    assert item["reason"] == "low_confidence"
    assert item["replaces"] is None
    assert len(item["sources"]) == 1
