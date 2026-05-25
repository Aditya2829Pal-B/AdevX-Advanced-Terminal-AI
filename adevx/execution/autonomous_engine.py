"""Autonomous reasoning engine: ReAct + plan-execute + reflection loops."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from adevx.agents.collaboration import CollaborationManager
from adevx.core.autonomy_models import Checkpoint, ExecutionNode, ReflectionReport, ReviewAction
from adevx.core.models import AssistantResponse, DomainEvent, UserRequest
from adevx.execution.checkpoint_store import CheckpointStore
from adevx.execution.execution_graph import ExecutionGraph
from adevx.execution.reflection import ReflectionEngine
from adevx.memory.working import ScratchpadMemory, WorkingMemory
from adevx.runtime.cancellation import CancellationToken
from adevx.runtime.event_bus import AsyncEventBus
from adevx.telemetry.logger import StructuredLogger


@dataclass(slots=True)
class ReasoningTrace:
    request_id: str
    logs: list[str] = field(default_factory=list)
    reflections: list[ReflectionReport] = field(default_factory=list)
    token_budget: int = 6000
    token_used: int = 0
    replans: int = 0
    retries: int = 0
    spawned_subtasks: int = 0

    def add_log(self, text: str) -> None:
        line = text.strip()
        if not line:
            return
        self.logs.append(line)
        self.token_used += max(1, len(line) // 4)


class AutonomousReasoningEngine:
    def __init__(
        self,
        *,
        collaboration: CollaborationManager,
        reflection: ReflectionEngine,
        checkpoints: CheckpointStore,
        scratchpad: ScratchpadMemory,
        working_memory: WorkingMemory,
        event_bus: AsyncEventBus,
        logger: StructuredLogger,
        max_iterations: int = 24,
        max_parallel: int = 3,
    ) -> None:
        self.collab = collaboration
        self.reflection = reflection
        self.checkpoints = checkpoints
        self.scratchpad = scratchpad
        self.working_memory = working_memory
        self.event_bus = event_bus
        self.logger = logger
        self.max_iterations = max_iterations
        self.max_parallel = max_parallel

    async def run(
        self,
        request: UserRequest,
        cancel_token: CancellationToken | None = None,
    ) -> AssistantResponse:
        token = cancel_token or CancellationToken()
        trace = ReasoningTrace(request_id=request.request_id)
        self.scratchpad.clear()
        self.scratchpad.add("system", f"Autonomous run started for {request.request_id}")
        trace.add_log("ReAct loop started.")

        plan = await self.collab.planner.plan(request)
        trace.add_log(f"Selected plan {plan.selected_plan.candidate.plan_id} with confidence {plan.selected_plan.candidate.confidence:.2f}")
        trace.add_log("Tree-of-thought trace:\n" + plan.thought_trace)
        tasks = plan.selected_plan.candidate.tasks
        graph = ExecutionGraph(tasks)

        research_context = await self.collab.researcher.gather(request, plan.goal)
        trace.add_log("Research context collected from RAG, long-term memory, and working memory.")

        await self._emit("autonomy.plan.selected", request, {"plan_id": plan.selected_plan.candidate.plan_id})

        iteration = 0
        while not graph.all_done() and iteration < self.max_iterations:
            token.raise_if_cancelled()
            iteration += 1
            trace.add_log(f"Iteration {iteration}: evaluating ready nodes.")
            ready = graph.ready_nodes()
            if not ready:
                if graph.has_failures():
                    trace.add_log("No ready nodes and failures present; stopping loop.")
                    break
                await asyncio.sleep(0.02)
                continue

            await self._emit(
                "autonomy.iteration",
                request,
                {"iteration": iteration, "ready_count": len(ready)},
            )

            outcomes = await self._run_ready_nodes(
                request=request,
                graph=graph,
                ready=ready,
                research_context=research_context,
                trace=trace,
                cancel_token=token,
            )
            for node, output, reflection in outcomes:
                trace.reflections.append(reflection)
                if reflection.action == ReviewAction.ACCEPT:
                    graph.mark_success(node.node_id, output=output, confidence=reflection.confidence)
                    trace.add_log(f"Node {node.node_id} accepted (conf={reflection.confidence:.2f}).")
                    spawned = self.collab.spawn_dynamic_subtasks(node, output)
                    if spawned:
                        self.collab.inject_subtasks(graph, spawned)
                        trace.spawned_subtasks += len(spawned)
                        trace.add_log(f"Spawned {len(spawned)} dynamic subtasks from {node.node_id}.")
                elif reflection.action == ReviewAction.RETRY and node.attempts < node.max_attempts:
                    trace.retries += 1
                    graph.reset_for_retry(node.node_id, revised_payload=reflection.revised_payload)
                    trace.add_log(f"Node {node.node_id} scheduled for retry after reflection.")
                elif reflection.action == ReviewAction.REPLAN:
                    trace.replans += 1
                    graph.mark_failure(node.node_id, "Reflection requested replan.")
                    rolled_back = await self.checkpoints.rollback_latest(request.request_id, graph)
                    trace.add_log(f"Replan requested for {node.node_id}. rollback={'ok' if rolled_back else 'none'}.")
                    if rolled_back:
                        graph.reset_for_retry(node.node_id, revised_payload=reflection.revised_payload)
                else:
                    graph.mark_failure(node.node_id, "Reflection halted execution.")
                    trace.add_log(f"Node {node.node_id} halted by reviewer.")

            if trace.token_used >= trace.token_budget:
                trace.add_log("Token budget reached. Stopping autonomous loop.")
                break

        if graph.all_done() and not graph.has_failures():
            summary = self._render_success_summary(graph, trace)
        else:
            summary = self._render_failure_summary(graph, trace)

        await self._emit(
            "autonomy.completed",
            request,
            {
                "iterations": iteration,
                "token_used": trace.token_used,
                "retries": trace.retries,
                "replans": trace.replans,
                "spawned_subtasks": trace.spawned_subtasks,
            },
        )
        self.logger.info(
            "autonomy.run.completed",
            request_id=request.request_id,
            iterations=iteration,
            token_used=trace.token_used,
            retries=trace.retries,
            replans=trace.replans,
            spawned_subtasks=trace.spawned_subtasks,
        )
        return AssistantResponse(
            request_id=request.request_id,
            text=summary,
            provider="autonomous-engine",
            mode=request.mode,
            metadata={
                "iterations": iteration,
                "trace_logs": trace.logs[-80:],
                "token_used": trace.token_used,
                "retries": trace.retries,
                "replans": trace.replans,
                "spawned_subtasks": trace.spawned_subtasks,
            },
        )

    async def _run_ready_nodes(
        self,
        *,
        request: UserRequest,
        graph: ExecutionGraph,
        ready: list[ExecutionNode],
        research_context: dict[str, str],
        trace: ReasoningTrace,
        cancel_token: CancellationToken,
    ) -> list[tuple[ExecutionNode, str, ReflectionReport]]:
        sem = asyncio.Semaphore(self.max_parallel)
        tasks = [
            asyncio.create_task(
                self._execute_one_node(
                    request=request,
                    graph=graph,
                    node=node,
                    research_context=research_context,
                    trace=trace,
                    sem=sem,
                    cancel_token=cancel_token,
                )
            )
            for node in ready
        ]
        return await asyncio.gather(*tasks)

    async def _execute_one_node(
        self,
        *,
        request: UserRequest,
        graph: ExecutionGraph,
        node: ExecutionNode,
        research_context: dict[str, str],
        trace: ReasoningTrace,
        sem: asyncio.Semaphore,
        cancel_token: CancellationToken,
    ) -> tuple[ExecutionNode, str, ReflectionReport]:
        async with sem:
            cancel_token.raise_if_cancelled()
            await self.checkpoints.create(
                Checkpoint(
                    checkpoint_id=f"ck_{request.request_id}_{node.node_id}_{node.attempts}",
                    request_id=request.request_id,
                    step_index=node.attempts,
                    snapshot={"node_id": node.node_id},
                ),
                graph,
            )
            graph.mark_running(node.node_id)
            await self._emit("autonomy.node.started", request, {"node_id": node.node_id, "attempt": node.attempts})
            output, confidence = await self.collab.dispatch(request, node, research_context)
            node.output = output
            node.confidence = confidence
            reflection = self.reflection.review(node, output)
            await self._emit(
                "autonomy.node.reflected",
                request,
                {
                    "node_id": node.node_id,
                    "confidence": reflection.confidence,
                    "hallucination_risk": reflection.hallucination_risk,
                    "action": reflection.action.value,
                },
            )
            trace.add_log(
                f"Node {node.node_id}: conf={reflection.confidence:.2f}, hall={reflection.hallucination_risk:.2f}, action={reflection.action.value}"
            )
            return node, output, reflection

    async def _emit(self, name: str, request: UserRequest, payload: dict[str, Any]) -> None:
        await self.event_bus.publish(
            DomainEvent(
                name=name,
                payload={"request_id": request.request_id, **payload},
                correlation_id=request.request_id,
            )
        )

    @staticmethod
    def _render_success_summary(graph: ExecutionGraph, trace: ReasoningTrace) -> str:
        lines = ["Autonomous execution completed successfully."]
        confidences = [node.confidence for node in graph.nodes.values() if node.status.value == "succeeded"]
        if confidences:
            lines.append(f"Average confidence: {mean(confidences):.2f}")
        lines.append(f"Retries: {trace.retries}")
        lines.append(f"Replans: {trace.replans}")
        lines.append(f"Spawned subtasks: {trace.spawned_subtasks}")
        lines.append("Execution results:")
        for node_id in sorted(graph.nodes.keys()):
            node = graph.nodes[node_id]
            lines.append(f"- {node_id} [{node.status.value}] conf={node.confidence:.2f}")
            if node.output:
                lines.append(node.output.strip())
        lines.append("Reasoning trace:")
        lines.extend(f"- {line}" for line in trace.logs[-20:])
        return "\n".join(lines)

    @staticmethod
    def _render_failure_summary(graph: ExecutionGraph, trace: ReasoningTrace) -> str:
        lines = ["Autonomous execution ended with failures."]
        lines.append(f"Retries: {trace.retries}")
        lines.append(f"Replans: {trace.replans}")
        lines.append(f"Spawned subtasks: {trace.spawned_subtasks}")
        for node_id in sorted(graph.nodes.keys()):
            node = graph.nodes[node_id]
            lines.append(f"- {node_id} [{node.status.value}] attempts={node.attempts}")
            if node.error:
                lines.append(f"  error: {node.error}")
        lines.append("Recent reasoning trace:")
        lines.extend(f"- {line}" for line in trace.logs[-20:])
        return "\n".join(lines)
