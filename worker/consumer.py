"""
Worker: takes signals off the Redis queue and runs the pipeline on them.

    python -m worker.consumer              # run until stopped
    python -m worker.consumer --recover    # first put back signals a crashed worker left behind

Run one worker with --recover, or any number without it. Recovery assumes no other worker is
mid-signal.
"""
import argparse
import asyncio
import signal as os_signal

from core.config import get_settings
from core.logging import get_logger, setup_logging
from graph.client import close_driver, get_driver
from graph.schema import ensure_schema
from vector.client import close_pool, get_pool
from core.supabase import close_supabase_pool, get_supabase_pool
from worker import queue
from worker.processor import SignalProcessor

logger = get_logger("worker.consumer")


async def process_one(processor: SignalProcessor, timeout: int = 5) -> bool:
    """Handle one queued signal. Returns False if the queue was empty."""
    item = await queue.dequeue(timeout=timeout)
    if item is None:
        return False

    try:
        result = await processor.process(item.signal)
    except Exception as exc:  # a bad signal must not stop the worker
        retrying = await queue.fail(item, f"{type(exc).__name__}: {exc}")
        logger.exception(
            "Signal processing failed",
            extra={"signal_id": str(item.signal.id), "attempts": item.attempts + 1, "will_retry": retrying},
        )
        return True

    await queue.acknowledge(item)
    logger.info(
        "Signal processed from queue",
        extra={
            "signal_id": str(item.signal.id),
            "article_id": result.article_id,
            "status": result.status.value,
            "duplicate": result.duplicate,
        },
    )
    return True


async def run(stop: asyncio.Event | None = None, idle_timeout: int = 5, max_signals: int | None = None) -> int:
    """Process signals until `stop` is set or `max_signals` have been handled. Returns the count."""
    stop = stop or asyncio.Event()
    processor = SignalProcessor()
    handled = 0
    while not stop.is_set() and (max_signals is None or handled < max_signals):
        if await process_one(processor, timeout=idle_timeout):
            handled += 1
        elif get_settings().mock_stores:
            await asyncio.sleep(0.2)  # the in-memory queue does not block, so avoid spinning
    return handled


async def main(recover: bool) -> None:
    setup_logging()
    await get_driver()
    await ensure_schema()
    await get_pool()
    await get_supabase_pool()

    if recover:
        logger.info("Recovered in-flight signals", extra={"count": await queue.recover_in_flight()})

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info("Worker started")
    try:
        await run(stop)
    finally:
        logger.info("Worker stopping")
        await close_driver()
        await close_pool()
        await close_supabase_pool()
        await queue.close_redis()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recover", action="store_true", help="requeue signals left in `processing` by a crashed worker")
    asyncio.run(main(parser.parse_args().recover))
