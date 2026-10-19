import pytest
from httpx import AsyncClient, ASGITransport

from api.main import app

from tests.conftest import TEST_TENANT_ID


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    # Development mode: no API key, the tenant comes from a header.
    async with AsyncClient(transport=transport, base_url="http://test", headers={"X-Tenant-ID": TEST_TENANT_ID}) as ac:
        yield ac


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestIngestEndpoint:
    @pytest.mark.asyncio
    async def test_ingest_ticket(self, client):
        payload = {
            "tenant_id": TEST_TENANT_ID,
            "ticket_id": "123",
            "subject": "Dashboard not loading",
            "description": "The Analytics Dashboard is not loading for some users",
            "priority": "high",
            "status": "open",
        }

        response = await client.post("/ingest/ticket", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "signal_id" in data
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_ingest_slack(self, client):
        payload = {
            "tenant_id": TEST_TENANT_ID,
            "team_id": "T123",
            "event": {
                "ts": "1234567890.123456",
                "text": "Has anyone seen issues with the Export feature?",
                "channel": "C123",
                "user": "U123",
            },
        }

        response = await client.post("/ingest/slack", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "signal_id" in data

    @pytest.mark.asyncio
    async def test_ingest_pr(self, client):
        payload = {
            "tenant_id": TEST_TENANT_ID,
            "pull_request": {
                "number": 456,
                "title": "Fix authentication bug",
                "body": "This PR fixes the SSO login issue",
                "state": "open",
                "user": {"login": "developer"},
            },
            "repository": {"full_name": "org/repo"},
        }

        response = await client.post("/ingest/pr", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "signal_id" in data

    @pytest.mark.asyncio
    async def test_ingest_empty_text_fails(self, client):
        payload = {
            "tenant_id": TEST_TENANT_ID,
            "ticket_id": "123",
            "subject": "",
            "description": "",
        }

        response = await client.post("/ingest/ticket", json=payload)

        assert response.status_code == 400


class TestProcessEndpoint:
    @pytest.mark.asyncio
    async def test_process_signal_sync(self, client):
        payload = {
            "source_id": "doc-1",
            "raw_text": "The Dashboard feature allows users to view Analytics reports",
        }

        response = await client.post("/ingest/process/test-signal-1", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "article_id" in data
        assert "status" in data
        assert "confidence" in data
        assert data["status"] in ["published", "pending_review"]


class TestContextEndpoint:
    @pytest.mark.asyncio
    async def test_context_retrieval_empty(self, client):
        response = await client.get("/context", params={"query": "test query"})

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    @pytest.mark.asyncio
    async def test_context_returns_a_published_article_after_ingest(self, client, low_threshold):
        ingest_payload = {
            "source_id": "doc-1",
            "raw_text": "The Dashboard feature provides real-time Analytics and reporting capabilities",
        }
        processed = await client.post("/ingest/process/context-test-1", json=ingest_payload)
        assert processed.json()["status"] == "published"

        response = await client.get("/context", params={"query": "Dashboard Analytics"})

        assert response.status_code == 200
        results = response.json()["results"]
        assert [r["article_id"] for r in results] == [processed.json()["article_id"]]
        assert "real-time Analytics" in results[0]["body"]

    @pytest.mark.asyncio
    async def test_context_hides_an_article_that_is_waiting_for_review(self, client):
        ingest_payload = {"source_id": "doc-1", "raw_text": "The Dashboard feature provides Analytics"}
        processed = await client.post("/ingest/process/context-test-2", json=ingest_payload)
        assert processed.json()["status"] == "pending_review"

        response = await client.get("/context", params={"query": "Dashboard Analytics"})

        assert response.json()["results"] == []


class TestReviewEndpoint:
    @pytest.mark.asyncio
    async def test_review_queue_empty(self, client):
        response = await client.get("/review/queue")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_approve_nonexistent_article(self, client):
        response = await client.post(
            "/review/nonexistent-id/approve",
            json={"reviewer_id": "reviewer-1"},
        )

        assert response.status_code == 404


class TestReviewQueueContext:
    async def test_the_queue_says_why_an_article_is_waiting_and_what_it_was_built_from(self, client, low_threshold):
        low_threshold.CONFIDENCE_THRESHOLD = 0.99
        await client.post(
            "/ingest/process/s1",
            json={"source_id": "d1", "raw_text": "The Dashboard feature shows Analytics reports"},
            headers={"X-Tenant-ID": TEST_TENANT_ID},
        )
        items = (await client.get("/review/queue", headers={"X-Tenant-ID": TEST_TENANT_ID})).json()["items"]
        assert len(items) == 1
        assert items[0]["reason"] == "low_confidence"
        assert items[0]["replaces"] is None
        assert [s["source_id"] for s in items[0]["sources"]] == ["d1"]
