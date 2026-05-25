"""Tree-of-thought plan generation and scoring."""

from __future__ import annotations

from dataclasses import dataclass

from adevx.core.autonomy_models import (
    DecomposedTask,
    Goal,
    PlanCandidate,
    SelectedPlan,
    ThoughtNode,
)


@dataclass(slots=True)
class TokenBudget:
    total: int = 6000
    reserved_for_execution: int = 4200
    reserved_for_reflection: int = 900
    reserved_for_retries: int = 900

    @property
    def planning_budget(self) -> int:
        return max(500, self.total - self.reserved_for_execution - self.reserved_for_reflection - self.reserved_for_retries)


class TreeOfThoughtPlanner:
    def __init__(self, budget: TokenBudget | None = None) -> None:
        self.budget = budget or TokenBudget()

    def generate_candidates(self, goal: Goal, tasks: list[DecomposedTask]) -> tuple[list[ThoughtNode], list[PlanCandidate]]:
        thought_nodes = [
            ThoughtNode(
                thought_id="th_branch_fast",
                branch="fast",
                hypothesis="Prioritize shortest path with minimal tool calls.",
                score=0.68,
                rationale="Lower latency but medium verification coverage.",
            ),
            ThoughtNode(
                thought_id="th_branch_balanced",
                branch="balanced",
                hypothesis="Balance tool usage and verification depth.",
                score=0.84,
                rationale="Good reliability and acceptable latency.",
            ),
            ThoughtNode(
                thought_id="th_branch_deep",
                branch="deep",
                hypothesis="Maximize verification and alternative checks.",
                score=0.79,
                rationale="High reliability but slower execution.",
            ),
        ]

        fast_tasks = self._subset_tasks(tasks, keep_review=True)
        balanced_tasks = tasks
        deep_tasks = tasks + [
            DecomposedTask(
                task_id="t_extra_crosscheck",
                title="Cross-check Reasoning",
                description="Perform additional independent consistency check.",
                capability="agent.reviewer",
                depends_on=["t5_finalize" if any(t.task_id == "t5_finalize" for t in tasks) else tasks[-1].task_id],
                priority=6,
            )
        ]

        candidates = [
            PlanCandidate(
                plan_id="plan_fast",
                summary=f"Fast execution for goal: {goal.objective}",
                tasks=fast_tasks,
                strategy="react-fast",
                confidence=0.68,
                reasoning="Fewest steps, reduced verification.",
                estimated_tokens=int(self.budget.planning_budget * 0.35),
            ),
            PlanCandidate(
                plan_id="plan_balanced",
                summary=f"Balanced plan for goal: {goal.objective}",
                tasks=balanced_tasks,
                strategy="plan-execute-reflect",
                confidence=0.84,
                reasoning="Strong tradeoff between speed and correctness.",
                estimated_tokens=int(self.budget.planning_budget * 0.55),
            ),
            PlanCandidate(
                plan_id="plan_deep",
                summary=f"Deep verification plan for goal: {goal.objective}",
                tasks=deep_tasks,
                strategy="tot-reflect-deep",
                confidence=0.79,
                reasoning="Highest verification depth, more latency.",
                estimated_tokens=int(self.budget.planning_budget * 0.75),
            ),
        ]
        return thought_nodes, candidates

    def select(self, candidates: list[PlanCandidate], prefer_quality: bool = True) -> SelectedPlan:
        ranked = sorted(
            candidates,
            key=lambda c: (c.confidence, -c.estimated_tokens if prefer_quality else c.estimated_tokens),
            reverse=True,
        )
        return SelectedPlan(candidate=ranked[0])

    @staticmethod
    def _subset_tasks(tasks: list[DecomposedTask], keep_review: bool) -> list[DecomposedTask]:
        if keep_review:
            return [t for t in tasks if "review" in t.capability or "verify" in t.capability or "finalize" in t.task_id or "analyze" in t.task_id or "implement" in t.task_id or "execute" in t.task_id]
        return tasks[: max(2, len(tasks) - 1)]

