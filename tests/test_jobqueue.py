import asyncio
import time

import pytest
from conftest import run

from mcpcalc.jobqueue import JobQueue, QueueFull


async def slow(x):
    await asyncio.sleep(0.1)
    return x * 2


def timed(workers, jobs):
    async def go():
        queue = JobQueue(slow, workers=workers, maxsize=50, timeout=5)
        started = time.perf_counter()
        results = await asyncio.gather(*(queue.submit(i) for i in range(jobs)))
        elapsed = time.perf_counter() - started
        await queue.close()
        return results, elapsed
    return run(go())


def test_parallel_workers_speed_things_up():
    results, parallel = timed(workers=6, jobs=6)
    assert results == [0, 2, 4, 6, 8, 10]
    _, serial = timed(workers=1, jobs=6)
    assert serial > 0.5 and parallel < serial / 2


def test_full_queue_rejects_instead_of_blocking():
    async def go():
        queue = JobQueue(slow, workers=1, maxsize=1, timeout=5)
        tasks = [asyncio.create_task(queue.submit(i)) for i in range(5)]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        await queue.close()
        return outcomes

    outcomes = run(go())
    assert any(isinstance(o, QueueFull) for o in outcomes)
    assert any(o == 0 for o in outcomes)


def test_timeout():
    async def go():
        queue = JobQueue(slow, workers=1, maxsize=5, timeout=0.01)
        try:
            await queue.submit(1)
        finally:
            await queue.close()

    with pytest.raises(asyncio.TimeoutError):
        run(go())


def test_handler_errors_reach_the_caller_and_workers_survive():
    async def flaky(x):
        if x == 0:
            raise ValueError("bad job")
        return x

    async def go():
        queue = JobQueue(flaky, workers=1, maxsize=5, timeout=5)
        with pytest.raises(ValueError):
            await queue.submit(0)
        value = await queue.submit(7)
        await queue.close()
        return value

    assert run(go()) == 7


def test_queue_survives_a_change_of_event_loop():
    queue = JobQueue(slow, workers=2, maxsize=5, timeout=5)
    assert run(queue.submit(1)) == 2
    assert run(queue.submit(2)) == 4  # a brand-new event loop
