"""Execution pipeline for plan step scheduling and capability invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from adevx.core.capability_registry import InMemoryCapabilityRegistry
from adevx.core.models import ExecutionPlan, PlannerStep, UserRequest
from adevx.runtime.cancellation import CancellationToken


@dataclass(slots=True)
class StepExecutionRecord:
    step_id: str
    capability: str
    output: str
    success: bool
    error: str = ""


@dataclass(slots=True)
class PipelineResult:
    request_id: str
    records: list[StepExecutionRecord] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(r.success for r in self.records) if self.records else True

    def render_summary(self) -> str:
        lines: list[str] = []
        for rec in self.records:
            status = "OK" if rec.success else "FAIL"
            lines.append(f"[{status}] {rec.step_id} ({rec.capability})")
            if rec.output:
                lines.append(rec.output.strip())
            if rec.error:
                lines.append(f"Error: {rec.error}")
        return "\n".join(lines).strip()


class StepPipelineExecutor:
    def __init__(self, capabilities: InMemoryCapabilityRegistry) -> None:
        self.capabilities = capabilities

    async def execute(
        self,
        plan: ExecutionPlan,
        request: UserRequest,
        cancel_token: CancellationToken,
    ) -> PipelineResult:
        result = PipelineResult(request_id=request.request_id)
        # Deterministic execution order now; can be upgraded to DAG scheduler.
        for step in plan.steps:
            cancel_token.raise_if_cancelled()
            record = await self._run_step(step, request)
            result.records.append(record)
            if not record.success:
                break
        return result

    async def _run_step(self, step: PlannerStep, request: UserRequest) -> StepExecutionRecord:
        capability = self.capabilities.get(step.capability)
        if capability is None:
            return StepExecutionRecord(
                step_id=step.id,
                capability=step.capability,
                output="",
                success=False,
                error=f"Capability '{step.capability}' is not registered.",
            )
        try:
            output = await capability.execute(step.input_payload, request)
            return StepExecutionRecord(
                step_id=step.id,
                capability=step.capability,
                output=output,
                success=True,
            )
        except Exception as exc:
            return StepExecutionRecord(
                step_id=step.id,
                capability=step.capability,
                output="",
                success=False,
                error=str(exc),
            )
