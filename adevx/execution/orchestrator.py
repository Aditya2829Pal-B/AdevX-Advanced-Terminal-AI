"""Top-level request orchestrator with event-driven lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adevx.core.contracts import EventBus, Planner
from adevx.core.models import AssistantResponse, DomainEvent, UserRequest
from adevx.execution.pipeline import StepPipelineExecutor
from adevx.runtime.cancellation import CancellationToken


@dataclass(slots=True)
class OrchestratorDependencies:
    planner: Planner
    pipeline: StepPipelineExecutor
    event_bus: EventBus


class ExecutionOrchestrator:
    def __init__(self, deps: OrchestratorDependencies) -> None:
        self._deps = deps

    async def handle_request(
        self,
        request: UserRequest,
        cancel_token: CancellationToken | None = None,
        context: dict[str, Any] | None = None,
    ) -> AssistantResponse:
        token = cancel_token or CancellationToken()
        ctx = context or {}

        await self._deps.event_bus.publish(
            DomainEvent(
                name="request.received",
                payload={"request_id": request.request_id, "mode": request.mode},
                correlation_id=request.request_id,
            )
        )

        plan = await self._deps.planner.build_plan(request, ctx)
        await self._deps.event_bus.publish(
            DomainEvent(
                name="plan.created",
                payload={"request_id": request.request_id, "steps": len(plan.steps)},
                correlation_id=request.request_id,
            )
        )

        pipeline_result = await self._deps.pipeline.execute(plan, request, token)
        await self._deps.event_bus.publish(
            DomainEvent(
                name="execution.completed",
                payload={
                    "request_id": request.request_id,
                    "success": pipeline_result.success,
                    "steps": len(pipeline_result.records),
                },
                correlation_id=request.request_id,
            )
        )

        summary = pipeline_result.render_summary() or "No execution output."
        response = AssistantResponse(
            request_id=request.request_id,
            mode=request.mode,
            text=summary,
            metadata={"pipeline_success": pipeline_result.success},
        )
        await self._deps.event_bus.publish(
            DomainEvent(
                name="response.ready",
                payload={"request_id": request.request_id},
                correlation_id=request.request_id,
            )
        )
        return response

