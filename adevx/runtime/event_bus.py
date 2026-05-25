"""Async in-process event bus for event-driven orchestration."""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from adevx.core.models import DomainEvent

EventHandler = Callable[[DomainEvent], Any]


class AsyncEventBus:
    def __init__(self, queue_max_size: int = 1000) -> None:
        self._queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=queue_max_size)
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []
        self._worker: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker = asyncio.create_task(self._dispatch_loop(), name="adevx-eventbus-dispatch")

    async def stop(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        key = event_name.strip().lower()
        if key in {"*", "all"}:
            self._wildcard_handlers.append(handler)
            return
        self._handlers[key].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        await self._queue.put(event)

    async def _dispatch_loop(self) -> None:
        while self._running:
            event = await self._queue.get()
            await self._dispatch(event)
            self._queue.task_done()

    async def _dispatch(self, event: DomainEvent) -> None:
        handlers = list(self._handlers.get(event.name.lower(), []))
        handlers.extend(self._wildcard_handlers)
        if not handlers:
            return
        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await _coerce_awaitable(result)
            except Exception:
                # Handler failures should never crash the bus worker.
                continue


async def _coerce_awaitable(awaitable: Awaitable[Any]) -> Any:
    return await awaitable

