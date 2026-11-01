"""In-process event bus: store commits and render jobs -> WebSocket subscribers.

Publishers run on any thread (store commits happen in worker threads, renders in
the render pool); subscribers are asyncio queues bound to the server's event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

log = logging.getLogger(__name__)

MAX_QUEUE = 256


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()
        self._sequence = 0

    def publish(self, event: dict[str, Any]) -> None:
        """Deliver ``event`` to every subscriber. Safe to call from any thread."""
        with self._lock:
            self._sequence += 1
            payload = {**event, "seq": self._sequence, "time": time.time()}
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_offer, queue, payload)
            except RuntimeError:  # loop closed
                with self._lock:
                    self._subscribers.discard((loop, queue))

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        entry = (loop, queue)
        with self._lock:
            self._subscribers.add(entry)
        try:
            yield queue
        finally:
            with self._lock:
                self._subscribers.discard(entry)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


def _offer(queue: asyncio.Queue, payload: dict[str, Any]) -> None:
    if queue.full():  # slow client: drop the oldest event, keep the newest
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
    queue.put_nowait(payload)
