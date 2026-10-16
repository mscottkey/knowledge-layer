"""
The signal queue on real Redis, and the worker carrying a signal through real Neo4j and Postgres.
Skipped unless REDIS_URL is set as well as the store variables.
"""
import os

import pytest
import pytest_asyncio

from models.signals import KnowledgeSignal, SourceType
from tests_integration.test_lifecycle import served
from worker import queue
from worker.consumer import process_one
from worker.processor import SignalProcessor

pytestmark = pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="needs REDIS_URL")


@pytest_asyncio.fixture(autouse=True)
async def clean_queue():
    client = await queue.get_redis()
    await client.delete(queue.QUEUE_KEY, queue.PROCESSING_KEY, queue.FAILED_KEY)
    yield
    await client.delete(queue.QUEUE_KEY, queue.PROCESSING_KEY, queue.FAILED_KEY)
    await queue.close_redis()


def signal_for(tenant: str, text: str, source_id: str = "s-1") -> KnowledgeSignal:
    return KnowledgeSignal.from_source(tenant, SourceType.ticket, source_id, text)


async def test_first_in_first_out_and_acknowledgement(tenant):
    first, second = signal_for(tenant, "first Dashboard"), signal_for(tenant, "second Dashboard")
    await queue.enqueue(first)
    await queue.enqueue(second)

    item = await queue.dequeue(timeout=1)
    assert item.signal.id == first.id
    assert (await queue.depth())["processing"] == 1
    await queue.acknowledge(item)
    assert (await queue.dequeue(timeout=1)).signal.id == second.id


async def test_an_empty_queue_times_out_instead_of_hanging():
    assert await queue.dequeue(timeout=1) is None


async def test_failures_are_retried_then_parked_with_their_error(tenant):
    await queue.enqueue(signal_for(tenant, "Dashboard"))
    for _ in range(queue.MAX_ATTEMPTS):
        await queue.fail(await queue.dequeue(timeout=1), "boom")

    assert await queue.depth() == {"queued": 0, "processing": 0, "failed": 1}
    parked = await (await queue.get_redis()).lrange(queue.FAILED_KEY, 0, -1)
    assert "boom" in parked[0]


async def test_recovery_after_a_crash_keeps_the_order(tenant):
    first, second = signal_for(tenant, "first Dashboard"), signal_for(tenant, "second Dashboard")
    await queue.enqueue(first)
    await queue.enqueue(second)
    await queue.dequeue(timeout=1)
    await queue.dequeue(timeout=1)  # the worker dies here

    assert await queue.recover_in_flight() == 2
    assert (await queue.dequeue(timeout=1)).signal.id == first.id


async def test_an_ingested_ticket_reaches_agents_once_the_worker_runs(client, tenant, threshold):
    threshold(0.0)
    response = await client.post(
        "/ingest/ticket",
        json={"ticket_id": "t-1", "subject": "Dashboard", "description": "The Dashboard feature shows Analytics reports"},
    )
    assert response.status_code == 202
    assert await served(client, tenant) == []  # accepted, not yet processed

    assert await process_one(SignalProcessor(), timeout=1) is True

    assert await queue.depth() == {"queued": 0, "processing": 0, "failed": 0}
    results = await served(client, tenant)
    assert len(results) == 1
