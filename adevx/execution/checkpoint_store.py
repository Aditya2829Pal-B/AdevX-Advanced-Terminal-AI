"""Checkpoint store and rollback mechanics for autonomous execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from adevx.core.autonomy_models import Checkpoint
from adevx.execution.execution_graph import ExecutionGraph, GraphSnapshot


@dataclass(slots=True)
class StoredCheckpoint:
    checkpoint: Checkpoint
    graph_snapshot: GraphSnapshot


class CheckpointStore:
    def __init__(self, max_checkpoints: int = 200) -> None:
        self.max_checkpoints = max_checkpoints
        self._checkpoints: list[StoredCheckpoint] = []
        self._lock = asyncio.Lock()

    async def create(self, checkpoint: Checkpoint, graph: ExecutionGraph) -> None:
        async with self._lock:
            self._checkpoints.append(
                StoredCheckpoint(
                    checkpoint=checkpoint,
                    graph_snapshot=graph.snapshot(),
                )
            )
            if len(self._checkpoints) > self.max_checkpoints:
                del self._checkpoints[0 : len(self._checkpoints) - self.max_checkpoints]

    async def latest_for_request(self, request_id: str) -> StoredCheckpoint | None:
        async with self._lock:
            for item in reversed(self._checkpoints):
                if item.checkpoint.request_id == request_id:
                    return item
            return None

    async def rollback_latest(self, request_id: str, graph: ExecutionGraph) -> bool:
        item = await self.latest_for_request(request_id)
        if item is None:
            return False
        graph.restore(item.graph_snapshot)
        return True

