"""In-memory metrics sink with observability hooks."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from adevx.core.models import DomainEvent


class InMemoryMetrics:
    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._event_count = 0
        self._lock = asyncio.Lock()

    async def emit(self, metric: str, value: float, tags: dict[str, str] | None = None) -> None:
        async with self._lock:
            self._counters[metric] += float(value)
            if tags:
                for key, val in tags.items():
                    self._counters[f"{metric}.{key}.{val}"] += float(value)

    async def log_event(self, event: DomainEvent) -> None:
        async with self._lock:
            self._event_count += 1
            self._counters[f"events.{event.name}"] += 1

    async def snapshot(self) -> dict[str, float]:
        async with self._lock:
            data = dict(self._counters)
            data["events.total"] = float(self._event_count)
            return data

