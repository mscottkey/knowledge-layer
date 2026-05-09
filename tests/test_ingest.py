import pytest
from httpx import AsyncClient, ASGITransport

from api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
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
            "tenant_id": "test-tenant",
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
            "tenant_id": "test-tenant",
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
            "tenant_id": "test-tenant",
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
            "tenant_id": "test-tenant",
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
            "tenant_id": "test-tenant",
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
        response = await client.get(
            "/context",
            params={"query": "test query", "tenant_id": "test-tenant"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    @pytest.mark.asyncio
    async def test_context_retrieval_after_ingest(self, client):
        ingest_payload = {
            "tenant_id": "test-tenant",
            "source_id": "doc-1",
            "raw_text": "The Dashboard feature provides real-time Analytics and reporting capabilities",
        }
        await client.post("/ingest/process/context-test-1", json=ingest_payload)

        response = await client.get(
            "/context",
            params={"query": "Dashboard Analytics", "tenant_id": "test-tenant"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data


class TestReviewEndpoint:
    @pytest.mark.asyncio
    async def test_review_queue_empty(self, client):
        response = await client.get(
            "/review/queue",
            params={"tenant_id": "test-tenant"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_approve_nonexistent_article(self, client):
        response = await client.post(
            "/review/nonexistent-id/approve",
            params={"tenant_id": "test-tenant"},
            json={"reviewer_id": "reviewer-1"},
        )

        assert response.status_code == 404
