from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from core.auth import authenticate_api_key, create_api_key, hash_api_key, revoke_api_key
from core.supabase import get_supabase_pool
from graph import queries
from tests.conftest import OTHER_TENANT_ID, TEST_TENANT_ID
from worker import queue

TENANT = UUID(TEST_TENANT_ID)
TICKET = {"ticket_id": "1", "subject": "Dashboard", "description": "The Dashboard feature is slow"}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def key_for(scopes, tenant: UUID = TENANT, **kwargs) -> dict[str, str]:
    created = await create_api_key(tenant, "test key", scopes, **kwargs)
    return {"X-API-Key": created.key}


class TestWhenAuthIsRequired:
    @pytest.fixture(autouse=True)
    def _enforce(self, require_auth):
        pass

    @pytest.mark.parametrize(
        "method,path,kwargs",
        [
            ("get", "/context", {"params": {"query": "x"}}),
            ("post", "/ingest/ticket", {"json": TICKET}),
            ("get", "/review/queue", {}),
        ],
    )
    async def test_requests_without_a_key_are_refused(self, client, method, path, kwargs):
        response = await getattr(client, method)(path, **kwargs)
        assert response.status_code == 401

    async def test_a_tenant_header_is_not_a_credential(self, client):
        response = await client.get("/context", params={"query": "x"}, headers={"X-Tenant-ID": TEST_TENANT_ID})
        assert response.status_code == 401

    async def test_unknown_and_malformed_keys_are_refused(self, client):
        for bad in ("kl_live_notarealkey", "not-even-the-right-shape", ""):
            headers = {"X-API-Key": bad} if bad else {}
            response = await client.get("/context", params={"query": "x"}, headers=headers)
            assert response.status_code == 401

    async def test_the_key_is_stored_hashed_not_in_plaintext(self):
        created = await create_api_key(TENANT, "k", ["read"])
        pool = await get_supabase_pool()
        assert created.key.startswith("kl_live_")
        assert hash_api_key(created.key) in pool.api_keys
        assert created.key not in str(pool.api_keys)

    async def test_a_read_key_can_read_but_not_write_or_review(self, client):
        headers = await key_for(["read"])
        assert (await client.get("/context", params={"query": "x"}, headers=headers)).status_code == 200
        assert (await client.post("/ingest/ticket", json=TICKET, headers=headers)).status_code == 403
        assert (await client.get("/review/queue", headers=headers)).status_code == 403

    async def test_a_write_key_can_ingest_but_not_review(self, client):
        headers = await key_for(["write"])
        assert (await client.post("/ingest/ticket", json=TICKET, headers=headers)).status_code == 202
        assert (await client.get("/review/queue", headers=headers)).status_code == 403
        assert (await client.post("/review/x/approve", json={}, headers=headers)).status_code == 403

    async def test_a_review_key_can_act_on_the_queue(self, client):
        headers = await key_for(["review"])
        assert (await client.get("/review/queue", headers=headers)).status_code == 200

    async def test_an_admin_key_can_do_everything(self, client):
        headers = await key_for(["admin"])
        assert (await client.get("/context", params={"query": "x"}, headers=headers)).status_code == 200
        assert (await client.post("/ingest/ticket", json=TICKET, headers=headers)).status_code == 202
        assert (await client.get("/review/queue", headers=headers)).status_code == 200

    async def test_the_tenant_comes_from_the_key_not_from_the_payload(self, client):
        headers = await key_for(["write"])
        payload = {**TICKET, "tenant_id": OTHER_TENANT_ID, "account_id": OTHER_TENANT_ID}
        assert (await client.post("/ingest/ticket", json=payload, headers=headers)).status_code == 202
        item = await queue.dequeue()
        assert item.signal.tenant_id == TEST_TENANT_ID

    async def test_a_key_cannot_be_pointed_at_another_tenant(self, client):
        headers = await key_for(["read", "review", "write"])
        assert (await client.get("/context", params={"query": "x", "tenant_id": OTHER_TENANT_ID}, headers=headers)).status_code == 403
        assert (await client.get("/review/queue", params={"tenant_id": OTHER_TENANT_ID}, headers=headers)).status_code == 403
        assert (await client.get("/review/queue", headers={**headers, "X-Tenant-ID": OTHER_TENANT_ID})).status_code == 403
        sync = await client.post(
            "/ingest/process/s1",
            json={"source_id": "d", "raw_text": "The Dashboard feature", "tenant_id": OTHER_TENANT_ID},
            headers=headers,
        )
        assert sync.status_code == 403
        # Naming the key's own tenant is fine.
        assert (await client.get("/context", params={"query": "x", "tenant_id": TEST_TENANT_ID}, headers=headers)).status_code == 200

    async def test_each_tenant_only_sees_its_own_review_queue(self, client, low_threshold):
        mine = await key_for(["admin"])
        theirs = await key_for(["admin"], tenant=UUID(OTHER_TENANT_ID))
        low_threshold.CONFIDENCE_THRESHOLD = 0.99
        await client.post("/ingest/process/s1", json={"source_id": "d", "raw_text": "The Dashboard feature"}, headers=mine)

        assert len((await client.get("/review/queue", headers=mine)).json()["items"]) == 1
        assert (await client.get("/review/queue", headers=theirs)).json()["items"] == []

    async def test_revoked_and_expired_keys_stop_working(self, client):
        created = await create_api_key(TENANT, "k", ["read"])
        headers = {"X-API-Key": created.key}
        assert (await client.get("/context", params={"query": "x"}, headers=headers)).status_code == 200

        assert await revoke_api_key(created.id, TENANT) is True
        assert (await client.get("/context", params={"query": "x"}, headers=headers)).status_code == 401
        assert await revoke_api_key(created.id, TENANT) is False

        expired = await key_for(["read"], expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        assert (await client.get("/context", params={"query": "x"}, headers=expired)).status_code == 401
        valid_for_now = await key_for(["read"], expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert (await client.get("/context", params={"query": "x"}, headers=valid_for_now)).status_code == 200

    async def test_another_tenants_key_cannot_revoke_this_one(self):
        created = await create_api_key(TENANT, "k", ["read"])
        assert await revoke_api_key(created.id, UUID(OTHER_TENANT_ID)) is False
        assert await authenticate_api_key(created.key) is not None

    async def test_use_is_recorded(self, client):
        created = await create_api_key(TENANT, "k", ["read"])
        for _ in range(3):
            await client.get("/context", params={"query": "x"}, headers={"X-API-Key": created.key})
        row = (await get_supabase_pool()).api_keys[hash_api_key(created.key)]
        assert row["total_requests"] == 3 and row["last_used_at"] is not None

    async def test_unknown_scopes_cannot_be_issued(self):
        with pytest.raises(ValueError):
            await create_api_key(TENANT, "k", ["read", "superuser"])

    async def test_the_reviewer_is_the_key_whatever_the_request_claims(self, client, monkeypatch, low_threshold):
        low_threshold.CONFIDENCE_THRESHOLD = 0.99
        headers = await key_for(["admin"])
        processed = await client.post("/ingest/process/s1", json={"source_id": "d", "raw_text": "The Dashboard feature"}, headers=headers)
        seen = {}

        async def capture(**kwargs):
            seen.update(kwargs)
            return "event-1"

        monkeypatch.setattr(queries, "create_review_event_node", capture)
        response = await client.post(
            f"/review/{processed.json()['article_id']}/approve", json={"reviewer_id": "the-ceo"}, headers=headers
        )
        assert response.status_code == 200
        assert seen["reviewer_id"].startswith("key:")
        assert seen["reviewer_id"] != "the-ceo"


class TestInDevelopment:
    """No API key: the tenant comes from X-Tenant-ID or the query string."""

    async def test_a_tenant_header_is_accepted(self, client):
        response = await client.get("/review/queue", headers={"X-Tenant-ID": TEST_TENANT_ID})
        assert response.status_code == 200

    async def test_the_tenant_can_come_from_the_query_string(self, client):
        assert (await client.get("/review/queue", params={"tenant_id": TEST_TENANT_ID})).status_code == 200

    async def test_a_missing_tenant_is_refused(self, client):
        assert (await client.get("/review/queue")).status_code == 401

    async def test_a_tenant_that_is_not_a_uuid_is_a_client_error_not_a_crash(self, client):
        response = await client.post(
            "/ingest/process/my-signal-id",
            json={"source_id": "doc-1", "raw_text": "The Dashboard feature"},
            headers={"X-Tenant-ID": "my-tenant"},
        )
        assert response.status_code == 400
        assert "UUID" in response.json()["detail"]

    async def test_an_api_key_still_wins_over_the_tenant_header(self, client):
        headers = await key_for(["read"], tenant=UUID(OTHER_TENANT_ID))
        response = await client.get("/context", params={"query": "x"}, headers={**headers, "X-Tenant-ID": TEST_TENANT_ID})
        assert response.status_code == 403


class TestCors:
    async def test_only_configured_origins_are_allowed(self, client):
        preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-api-key"}
        allowed = await client.options("/context", headers={"Origin": "http://localhost:3000", **preflight})
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert "access-control-allow-credentials" not in allowed.headers

        refused = await client.options("/context", headers={"Origin": "https://evil.example", **preflight})
        assert "access-control-allow-origin" not in refused.headers
