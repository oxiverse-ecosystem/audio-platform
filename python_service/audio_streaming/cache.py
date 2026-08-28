"""Bounded caches and executor gates that prevent personalization work from growing without limit."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar


T = TypeVar("T")


class BoundedAsyncByteCache:
    """LRU byte cache with single-flight construction for identical segment requests."""

    def __init__(self, max_bytes: int):
        self._max_bytes = max_bytes
        self._values: OrderedDict[str, bytes] = OrderedDict()
        self._bytes = 0
        self._inflight: dict[str, asyncio.Task[bytes]] = {}
        self._lock = asyncio.Lock()

    @property
    def bytes_used(self) -> int:
        return self._bytes

    @property
    def entries(self) -> int:
        return len(self._values)

    async def get_or_create(self, key: str, factory: Callable[[], Awaitable[bytes]]) -> bytes:
        """Return cached bytes or perform one bounded build shared by all waiting callers."""

        async with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
                return value
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(factory(), name=f"segment-build:{key}")
                self._inflight[key] = task
        try:
            value = await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    self._inflight.pop(key, None)
        async with self._lock:
            existing = self._values.get(key)
            if existing is not None:
                self._values.move_to_end(key)
                return existing
            if len(value) > self._max_bytes:
                return value
            self._values[key] = value
            self._bytes += len(value)
            while self._bytes > self._max_bytes and self._values:
                _, evicted = self._values.popitem(last=False)
                self._bytes -= len(evicted)
            return value

    async def close(self) -> None:
        async with self._lock:
            pending = list(self._inflight.values())
            self._inflight.clear()
            self._values.clear()
            self._bytes = 0
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


class BoundedWorkerPool:
    """Dedicated finite thread pool with a gate that remains occupied after request cancellation."""

    def __init__(self, max_workers: int, max_pending: int | None = None):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="audio-dsp")
        self._gate = asyncio.Semaphore(max_workers)
        self._admission = asyncio.BoundedSemaphore(max_pending or max_workers * 2)

    async def run(self, operation: Callable[[], T], timeout_seconds: float = 30.0) -> T:
        """Run blocking codec/DSP work without allowing caller cancellation to leak new work."""

        async def bounded() -> T:
            try:
                await asyncio.wait_for(self._admission.acquire(), timeout=0.005)
            except TimeoutError as exc:
                raise BackpressureError("personalization queue is at capacity") from exc
            try:
                async with self._gate:
                    loop = asyncio.get_running_loop()
                    return await asyncio.wait_for(loop.run_in_executor(self._executor, operation), timeout_seconds)
            finally:
                self._admission.release()

        task: asyncio.Task[T] = asyncio.create_task(bounded())
        return await asyncio.shield(task)

    async def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class BackpressureError(RuntimeError):
    """Raised when a bounded work queue refuses new expensive media work."""


class RequestRateLimiter:
    """Bounded in-memory rolling-window limiter keyed by a one-way request identity hash.

    A distributed deployment should replace this intentionally local guard with an atomic shared
    limiter at the API gateway or datastore. It still protects a single MVP process from a burst.
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0, max_keys: int = 10_000):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def opaque_key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    async def allow(self, source: str) -> tuple[bool, int]:
        """Return whether one request is admitted and an integer retry-after hint if not."""

        now = time.monotonic()
        key = self.opaque_key(source)
        async with self._lock:
            bucket = self._requests.get(key)
            if bucket is None:
                if len(self._requests) >= self._max_keys:
                    self._requests.popitem(last=False)
                bucket = deque()
                self._requests[key] = bucket
            self._requests.move_to_end(key)
            while bucket and bucket[0] <= now - self._window_seconds:
                bucket.popleft()
            if len(bucket) >= self._max_requests:
                return False, max(1, int(self._window_seconds - (now - bucket[0])) + 1)
            bucket.append(now)
            return True, 0
