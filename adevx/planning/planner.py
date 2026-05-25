"""Agentic planning engine with mode-aware heuristics."""

from __future__ import annotations

from adevx.core.models import ExecutionPlan, PlannerStep, UserRequest


class HeuristicPlanner:
    async def build_plan(self, request: UserRequest, context: dict) -> ExecutionPlan:
        text = request.text.lower()
        steps: list[PlannerStep] = []

        steps.append(
            PlannerStep(
                id="step_1_analyze",
                title="Analyze Request",
                description="Classify request intent and required capabilities.",
                capability="capability.classifier",
                input_payload={"text": request.text, "mode": request.mode},
            )
        )

        autonomous_signals = (
            "autonomous",
            "multi-step",
            "reasoning engine",
            "plan and execute",
            "tree-of-thought",
            "self-critique",
            "agent platform",
        )
        if any(signal in text for signal in autonomous_signals):
            steps.append(
                PlannerStep(
                    id="step_2_autonomous",
                    title="Run Autonomous Agent Loop",
                    description="Execute autonomous plan/reason/reflect cycle.",
                    capability="capability.autonomous",
                    input_payload={"text": request.text, "mode": request.mode},
                )
            )
            steps.append(
                PlannerStep(
                    id="step_3_verify",
                    title="Verify Output",
                    description="Run quality/safety validation checks.",
                    capability="capability.verify",
                    input_payload={"request_id": request.request_id},
                    depends_on=["step_2_autonomous"],
                )
            )
            return ExecutionPlan(
                request_id=request.request_id,
                steps=steps,
                summary="PLAN -> ANALYZE -> EXECUTE -> REFLECT -> IMPROVE",
            )

        if any(k in text for k in ("file", "write", "read", "search", "create")):
            steps.append(
                PlannerStep(
                    id="step_2_tooling",
                    title="Execute Tool Tasks",
                    description="Run workspace/file tools.",
                    capability="capability.tools",
                    input_payload={"text": request.text},
                )
            )
        elif any(k in text for k in ("code", "debug", "bug", "function")):
            steps.append(
                PlannerStep(
                    id="step_2_coding",
                    title="Solve Coding Task",
                    description="Use coding provider strategy and verification.",
                    capability="capability.coding",
                    input_payload={"text": request.text, "mode": request.mode},
                )
            )
        else:
            steps.append(
                PlannerStep(
                    id="step_2_chat",
                    title="Generate Assistant Response",
                    description="Produce answer using provider routing and context.",
                    capability="capability.chat",
                    input_payload={"text": request.text, "mode": request.mode},
                )
            )

        steps.append(
            PlannerStep(
                id="step_3_verify",
                title="Verify Output",
                description="Run quality/safety validation checks.",
                capability="capability.verify",
                input_payload={"request_id": request.request_id},
            )
        )

        return ExecutionPlan(
            request_id=request.request_id,
            steps=steps,
            summary="PLAN -> ANALYZE -> EXECUTE -> VERIFY -> IMPROVE",
        )
