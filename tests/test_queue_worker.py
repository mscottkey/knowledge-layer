from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from models.signals import KnowledgeSignal, SourceType
from tests.conftest import TEST_TENANT_ID
from worker import queue
from worker.consumer import process_one, run
from worker.processor import SignalProcessor


def make_signal(text: str = "The Dashboard feature is slow", source=SourceType.ticket) -> KnowledgeSignal:
    return KnowledgeSignal(tenant_id=TEST_TENANT_ID, source=source, source_id="s-1", raw_text=text)


class FailingProcessor:
    def __init__(self):
        self.calls = 0

    async def process(self, signal):
        self.calls += 1
        raise RuntimeError("model unavailable")


async def test_enqueue_and_dequeue_are_first_in_first_out():
    first, second = make_signal("first Dashboard"), make_signal("second Dashboard")
    await queue.enqueue(first)
    await queue.enqueue(second)
    assert (await queue.depth()) == {"queued": 2, "processing": 0, "failed": 0}

    assert (await queue.dequeue()).signal.id == first.id
    assert (await queue.dequeue()).signal.id == second.id
    assert await queue.dequeue() is None


async def test_a_signal_survives_the_round_trip():
    signal = make_signal(source=SourceType.slack)
    await queue.enqueue(signal)
    item = await queue.dequeue()
    assert item.signal == signal
    assert item.attempts == 0


async def test_a_dequeued_signal_waits_in_processing_until_acknowledged():
    await queue.enqueue(make_signal())
    item = await queue.dequeue()
    assert (await queue.depth())["processing"] == 1
    await queue.acknowledge(item)
    assert (await queue.depth()) == {"queued": 0, "processing": 0, "failed": 0}


async def test_a_failed_signal_is_retried_then_parked():
    await queue.enqueue(make_signal())
    attempts = []
    for _ in range(queue.MAX_ATTEMPTS):
        item = await queue.dequeue()
        attempts.append(item.attempts)
        retrying = await queue.fail(item, "boom")
        assert retrying is (len(attempts) < queue.MAX_ATTEMPTS)

    assert attempts == list(range(queue.MAX_ATTEMPTS))
    assert await queue.depth() == {"queued": 0, "processing": 0, "failed": 1}


async def test_recovery_returns_a_crashed_workers_signals_to_the_queue():
    await queue.enqueue(make_signal("one Dashboard"))
    await queue.enqueue(make_signal("two Dashboard"))
    first = await queue.dequeue()
    await queue.dequeue()  # the worker dies holding both

    assert await queue.recover_in_flight() == 2
    assert await queue.depth() == {"queued": 2, "processing": 0, "failed": 0}
    assert (await queue.dequeue()).signal.id == first.signal.id  # order is kept


async def test_ingest_enqueues_and_the_worker_turns_it_into_an_article(low_threshold):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/ingest/ticket",
            json={"ticket_id": "t-1", "subject": "Dashboard", "description": "The Dashboard feature is slow"},
            headers={"X-Tenant-ID": TEST_TENANT_ID},
        )
        assert response.status_code == 202
        assert (await queue.depth())["queued"] == 1

        assert await process_one(SignalProcessor()) is True
        assert await queue.depth() == {"queued": 0, "processing": 0, "failed": 0}

        context = await client.get("/context", params={"query": "Dashboard feature slow"}, headers={"X-Tenant-ID": TEST_TENANT_ID})
        assert context.status_code == 200
        assert context.json()["results"], "the worker should have published an article"


async def test_the_source_type_follows_the_endpoint_not_a_hardcoded_default():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Tenant-ID": TEST_TENANT_ID}
        await client.post("/ingest/ticket", json={"ticket_id": "1", "subject": "s", "description": "Dashboard"}, headers=headers)
        assert (await queue.dequeue()).signal.source == SourceType.ticket


async def test_a_signal_that_keeps_failing_ends_up_in_the_failed_list():
    await queue.enqueue(make_signal())
    processor = FailingProcessor()
    for _ in range(queue.MAX_ATTEMPTS):
        assert await process_one(processor) is True

    assert processor.calls == queue.MAX_ATTEMPTS
    assert await queue.depth() == {"queued": 0, "processing": 0, "failed": 1}
    assert await process_one(processor) is False  # and the worker is still running


async def test_one_bad_signal_does_not_stop_the_ones_behind_it(monkeypatch, low_threshold):
    good = make_signal("a good Dashboard signal")
    bad = make_signal("a bad Dashboard signal")
    await queue.enqueue(bad)
    await queue.enqueue(good)

    real = SignalProcessor.process

    async def flaky(self, signal):
        if signal.id == bad.id:
            raise RuntimeError("boom")
        return await real(self, signal)

    monkeypatch.setattr(SignalProcessor, "process", flaky)
    await run(max_signals=2 + queue.MAX_ATTEMPTS - 1)

    assert await queue.depth() == {"queued": 0, "processing": 0, "failed": 1}


async def test_a_replayed_signal_is_reported_as_a_duplicate(low_threshold):
    processor = SignalProcessor()
    first = await processor.process(make_signal())
    again = await processor.process(make_signal())
    assert first.duplicate is False
    assert again.duplicate is True
