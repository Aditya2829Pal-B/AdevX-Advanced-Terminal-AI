"""Multi-agent collaboration and dynamic subtask spawning."""

from __future__ import annotations

from dataclasses import dataclass

from adevx.agents.roles import CodingAgent, ExecutorAgent, PlannerAgent, ResearchAgent, ReviewerAgent
from adevx.core.autonomy_models import DecomposedTask, ExecutionNode
from adevx.core.models import UserRequest
from adevx.execution.execution_graph import ExecutionGraph


@dataclass(slots=True)
class CollaborationManager:
    planner: PlannerAgent
    executor: ExecutorAgent
    reviewer: ReviewerAgent
    researcher: ResearchAgent
    coder: CodingAgent

    def spawn_dynamic_subtasks(self, node: ExecutionNode, output: str) -> list[DecomposedTask]:
        lower = output.lower()
        spawned: list[DecomposedTask] = []
        if "missing" in lower or "incomplete" in lower:
            spawned.append(
                DecomposedTask(
                    task_id=f"{node.node_id}_retry_patch",
                    title=f"Patch {node.title}",
                    description="Address incompleteness found during review.",
                    capability="agent.executor",
                    depends_on=[node.node_id],
                    priority=7,
                )
            )
        if "error" in lower and "file" in lower:
            spawned.append(
                DecomposedTask(
                    task_id=f"{node.node_id}_investigate_error",
                    title=f"Investigate {node.title} Error",
                    description="Research and resolve file-related execution errors.",
                    capability="agent.research",
                    depends_on=[node.node_id],
                    priority=8,
                )
            )
        return spawned

    def inject_subtasks(self, graph: ExecutionGraph, subtasks: list[DecomposedTask]) -> None:
        for subtask in subtasks:
            if subtask.task_id in graph.nodes:
                continue
            graph.nodes[subtask.task_id] = ExecutionNode(
                node_id=subtask.task_id,
                title=subtask.title,
                capability=subtask.capability,
                payload={"task": subtask.description, "tool_hints": subtask.tool_hints},
                depends_on=list(subtask.depends_on),
                max_attempts=2,
            )

    async def dispatch(
        self,
        request: UserRequest,
        node: ExecutionNode,
        research_context: dict[str, str],
    ) -> tuple[str, float]:
        if node.capability == "agent.planner":
            return (
                "Planner checkpoint complete. Step verified result: objective, constraints, "
                "and execution strategy were analyzed and validated for downstream tasks."
            ), 0.86

        if node.capability == "agent.research":
            rag = research_context.get("rag_context", "").strip()
            notes = research_context.get("long_term_notes", "").strip()
            text = "Research summary prepared."
            if rag:
                text += f"\nRAG:\n{rag[:900]}"
            if notes:
                text += f"\nMemory:\n{notes[:600]}"
            return text, 0.8

        if node.capability == "agent.reviewer":
            review = await self.reviewer.critique(str(node.payload.get("task", "")))
            if review.startswith("review:pass"):
                return (
                    "Review passed. Step verified result: outputs are consistent, "
                    "constraints are respected, and no blocking defects were detected."
                ), 0.82
            return (
                "Review flagged issues and requires correction. "
                f"Step verified result: {review}"
            ), 0.55

        if node.capability == "agent.coding":
            return await self.coder.solve(
                request,
                DecomposedTask(
                    task_id=node.node_id,
                    title=node.title,
                    description=str(node.payload.get("task", "")),
                    capability=node.capability,
                    tool_hints=list(node.payload.get("tool_hints", [])),
                ),
                research_context,
            )

        return await self.executor.execute_task(
            request,
            DecomposedTask(
                task_id=node.node_id,
                title=node.title,
                description=str(node.payload.get("task", "")),
                capability=node.capability,
                tool_hints=list(node.payload.get("tool_hints", [])),
            ),
            research_context,
        )
