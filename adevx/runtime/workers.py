"""Background worker supervisor for async runtime tasks."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(slots=True)
class WorkerSpec:
    name: str
    factory: Callable[[], Awaitable[None]]


class BackgroundWorkerSupervisor:
    def __init__(self) -> None:
        self._workers: list[WorkerSpec] = []
        self._tasks: list[asyncio.Task[None]] = []

    def register(self, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        self._workers.append(WorkerSpec(name=name, factory=factory))

    async def start(self) -> None:
        if self._tasks:
            return
        for worker in self._workers:
            task = asyncio.create_task(worker.factory(), name=f"adevx-worker-{worker.name}")
            self._tasks.append(task)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

