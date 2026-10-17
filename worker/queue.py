"""
Signal queue on Redis, with acknowledgement and retries.

A signal moves queue -> processing when a worker takes it, and leaves processing when the worker
acknowledges it or gives up. If a worker dies mid-signal the item stays in `processing`, and
`recover_in_flight` puts it back. After MAX_ATTEMPTS failures a signal goes to the failed list
with its last error, where an operator can look at it.
"""
import json
from collections import deque
from dataclasses import dataclass

import redis.asyncio as redis

from core.config import get_settings
from core.logging import get_logger
from models.signals import KnowledgeSignal

logger = get_logger("worker.queue")

QUEUE_KEY = "knowledgelayer:signals"
PROCESSING_KEY = "knowledgelayer:signals:processing"
FAILED_KEY = "knowledgelayer:signals:failed"
MAX_ATTEMPTS = 3

_redis_client: redis.Redis | None = None

# In-memory stand-ins for mock mode, so the API and worker can be exercised without Redis.
_mock: dict[str, deque[str]] = {QUEUE_KEY: deque(), PROCESSING_KEY: deque(), FAILED_KEY: deque()}


@dataclass
class QueuedSignal:
    signal: KnowledgeSignal
    attempts: int
    raw: str  # the exact stored envelope, needed to acknowledge it


def _encode(signal: KnowledgeSignal, attempts: int = 0, error: str | None = None) -> str:
    envelope: dict = {"signal": signal.model_dump(mode="json"), "attempts": attempts}
    if error is not None:
        envelope["error"] = error
    return json.dumps(envelope)


def _decode(raw: str) -> tuple[KnowledgeSignal, int]:
    envelope = json.loads(raw)
    return KnowledgeSignal.model_validate(envelope["signal"]), int(envelope.get("attempts", 0))


async def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


def reset_mock_queue() -> None:
    for items in _mock.values():
        items.clear()


async def enqueue(signal: KnowledgeSignal, attempts: int = 0) -> None:
    raw = _encode(signal, attempts)
    if get_settings().mock_stores:
        _mock[QUEUE_KEY].appendleft(raw)
        return
    await (await get_redis()).lpush(QUEUE_KEY, raw)


async def dequeue(timeout: int = 5) -> QueuedSignal | None:
    """Take the oldest signal and park it in `processing`. Returns None if nothing arrived in time."""
    if get_settings().mock_stores:
        if not _mock[QUEUE_KEY]:
            return None
        raw = _mock[QUEUE_KEY].pop()
        _mock[PROCESSING_KEY].appendleft(raw)
    else:
        client = await get_redis()
        raw = await client.blmove(QUEUE_KEY, PROCESSING_KEY, timeout, "RIGHT", "LEFT")
        if raw is None:
            return None
    signal, attempts = _decode(raw)
    return QueuedSignal(signal=signal, attempts=attempts, raw=raw)


async def _remove_from_processing(raw: str) -> None:
    if get_settings().mock_stores:
        try:
            _mock[PROCESSING_KEY].remove(raw)
        except ValueError:
            pass
        return
    await (await get_redis()).lrem(PROCESSING_KEY, 1, raw)


async def acknowledge(item: QueuedSignal) -> None:
    await _remove_from_processing(item.raw)


async def fail(item: QueuedSignal, error: str) -> bool:
    """Retry the signal, or park it in the failed list. Returns True if it will be retried."""
    await _remove_from_processing(item.raw)
    attempts = item.attempts + 1
    if attempts < MAX_ATTEMPTS:
        await enqueue(item.signal, attempts)
        return True

    dead = _encode(item.signal, attempts, error)
    if get_settings().mock_stores:
        _mock[FAILED_KEY].appendleft(dead)
    else:
        await (await get_redis()).lpush(FAILED_KEY, dead)
    logger.error(
        "Signal failed permanently",
        extra={"signal_id": str(item.signal.id), "attempts": attempts, "error": error},
    )
    return False


async def recover_in_flight() -> int:
    """
    Put signals a dead worker left in `processing` back on the queue, at the front, oldest first.
    Run with a single worker.
    """
    moved = 0
    if get_settings().mock_stores:
        while _mock[PROCESSING_KEY]:
            _mock[QUEUE_KEY].append(_mock[PROCESSING_KEY].popleft())
            moved += 1
        return moved
    client = await get_redis()
    while await client.lmove(PROCESSING_KEY, QUEUE_KEY, "LEFT", "RIGHT"):
        moved += 1
    return moved


async def depth() -> dict[str, int]:
    if get_settings().mock_stores:
        return {"queued": len(_mock[QUEUE_KEY]), "processing": len(_mock[PROCESSING_KEY]), "failed": len(_mock[FAILED_KEY])}
    client = await get_redis()
    return {
        "queued": await client.llen(QUEUE_KEY),
        "processing": await client.llen(PROCESSING_KEY),
        "failed": await client.llen(FAILED_KEY),
    }
