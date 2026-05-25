"""Execution graph with dependency-aware parallel scheduling."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from adevx.core.autonomy_models import DecomposedTask, ExecutionNode, NodeStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class GraphSnapshot:
    created_at: datetime
    nodes: dict[str, dict[str, Any]]


class ExecutionGraph:
    def __init__(self, tasks: list[DecomposedTask]) -> None:
        self.nodes: dict[str, ExecutionNode] = {
            task.task_id: ExecutionNode(
                node_id=task.task_id,
                title=task.title,
                capability=task.capability,
                payload={"task": task.description, "tool_hints": task.tool_hints},
                depends_on=list(task.depends_on),
                max_attempts=3,
            )
            for task in tasks
        }

    def ready_nodes(self) -> list[ExecutionNode]:
        ready: list[ExecutionNode] = []
        for node in self.nodes.values():
            if node.status not in {NodeStatus.PENDING, NodeStatus.READY}:
                continue
            if self._deps_satisfied(node):
                node.status = NodeStatus.READY
                ready.append(node)
        return sorted(ready, key=lambda n: n.node_id)

    def mark_running(self, node_id: str) -> None:
        node = self.nodes[node_id]
        node.status = NodeStatus.RUNNING
        node.attempts += 1
        node.updated_at = _now()

    def mark_success(self, node_id: str, output: str, confidence: float) -> None:
        node = self.nodes[node_id]
        node.status = NodeStatus.SUCCEEDED
        node.output = output
        node.confidence = confidence
        node.updated_at = _now()

    def mark_failure(self, node_id: str, error: str) -> None:
        node = self.nodes[node_id]
        node.status = NodeStatus.FAILED
        node.error = error
        node.updated_at = _now()

    def reset_for_retry(self, node_id: str, revised_payload: dict[str, Any] | None = None) -> None:
        node = self.nodes[node_id]
        node.status = NodeStatus.PENDING
        node.error = ""
        if revised_payload:
            node.payload.update(revised_payload)
        node.updated_at = _now()

    def all_done(self) -> bool:
        return all(node.status in {NodeStatus.SUCCEEDED, NodeStatus.SKIPPED} for node in self.nodes.values())

    def has_failures(self) -> bool:
        return any(node.status == NodeStatus.FAILED for node in self.nodes.values())

    def snapshot(self) -> GraphSnapshot:
        return GraphSnapshot(
            created_at=_now(),
            nodes={
                node_id: {
                    "status": node.status.value,
                    "attempts": node.attempts,
                    "output": node.output,
                    "error": node.error,
                    "confidence": node.confidence,
                    "depends_on": list(node.depends_on),
                    "payload": dict(node.payload),
                }
                for node_id, node in self.nodes.items()
            },
        )

    def restore(self, snapshot: GraphSnapshot) -> None:
        for node_id, info in snapshot.nodes.items():
            if node_id not in self.nodes:
                continue
            node = self.nodes[node_id]
            node.status = NodeStatus(info.get("status", NodeStatus.PENDING.value))
            node.attempts = int(info.get("attempts", 0))
            node.output = str(info.get("output", ""))
            node.error = str(info.get("error", ""))
            node.confidence = float(info.get("confidence", 0.0))
            node.depends_on = list(info.get("depends_on", []))
            payload = info.get("payload", {})
            if isinstance(payload, dict):
                node.payload = dict(payload)
            node.updated_at = _now()

    async def run_parallel(
        self,
        execute_node,
        max_parallel: int = 3,
    ) -> None:
        sem = asyncio.Semaphore(max_parallel)
        while not self.all_done():
            ready = self.ready_nodes()
            if not ready:
                if self.has_failures():
                    break
                await asyncio.sleep(0.02)
                continue
            tasks = [asyncio.create_task(self._run_one(node, execute_node, sem)) for node in ready]
            await asyncio.gather(*tasks)

    async def _run_one(self, node: ExecutionNode, execute_node, sem: asyncio.Semaphore) -> None:
        async with sem:
            self.mark_running(node.node_id)
            try:
                output, confidence = await execute_node(node)
                self.mark_success(node.node_id, output=output, confidence=confidence)
            except Exception as exc:
                self.mark_failure(node.node_id, str(exc))

    def _deps_satisfied(self, node: ExecutionNode) -> bool:
        for dep in node.depends_on:
            dep_node = self.nodes.get(dep)
            if dep_node is None:
                return False
            if dep_node.status != NodeStatus.SUCCEEDED:
                return False
        return True

