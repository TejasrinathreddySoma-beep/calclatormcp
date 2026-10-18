"""Async job queue: bounded backlog, N workers, per-job timeout. Lets many MCP clients share one backend safely."""
from __future__ import annotations

import asyncio


class QueueFull(RuntimeError):
    """The backlog is full; the caller should retry later."""


class JobQueue:
    def __init__(self, handler, workers: int = 1, maxsize: int = 100, timeout: float = 30.0):
        self._handler, self._workers, self._maxsize, self._timeout = handler, max(1, workers), maxsize, timeout
        self._queue: asyncio.Queue | None = None
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def depth(self) -> int:
        return self._queue.qsize() if self._queue else 0

    def _ensure_started(self) -> None:
        loop = asyncio.get_running_loop()
        if self._queue is None or self._loop is not loop:  # (re)start if we were created on another event loop
            self._loop = loop
            self._queue = asyncio.Queue(self._maxsize)
            self._tasks = [asyncio.create_task(self._worker()) for _ in range(self._workers)]

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            args, future = await self._queue.get()
            try:
                if not future.cancelled():
                    future.set_result(await self._handler(*args))
            except Exception as ex:  # noqa: BLE001 - forwarded to the waiting caller
                if not future.done():
                    future.set_exception(ex)
            finally:
                self._queue.task_done()

    async def submit(self, *args):
        self._ensure_started()
        assert self._queue is not None
        future = asyncio.get_running_loop().create_future()
        try:
            self._queue.put_nowait((args, future))
        except asyncio.QueueFull:
            raise QueueFull("server busy: job queue is full") from None
        return await asyncio.wait_for(future, self._timeout)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks, self._queue = [], None
