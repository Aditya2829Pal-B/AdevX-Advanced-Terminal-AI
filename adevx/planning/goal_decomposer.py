"""Goal decomposition engine for autonomous execution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from adevx.core.autonomy_models import DecomposedTask, Goal


@dataclass(slots=True)
class GoalDecomposer:
    """Heuristic goal decomposition with mode/tool awareness."""

    def decompose(self, goal: Goal, preferred_mode: str = "chat") -> list[DecomposedTask]:
        text = goal.objective.strip()
        lower = text.lower()
        tasks: list[DecomposedTask] = []

        tasks.append(
            DecomposedTask(
                task_id="t1_analyze_goal",
                title="Analyze Goal",
                description="Understand objective, constraints, and acceptance criteria.",
                capability="agent.planner",
                priority=10,
            )
        )

        if self._needs_research(lower):
            tasks.append(
                DecomposedTask(
                    task_id="t2_research",
                    title="Research Context",
                    description="Collect supporting context from memory and project index.",
                    capability="agent.research",
                    depends_on=["t1_analyze_goal"],
                    priority=9,
                    parallel_group="ctx",
                )
            )

        if self._needs_coding(lower) or preferred_mode == "coding":
            tasks.append(
                DecomposedTask(
                    task_id="t3_implement",
                    title="Implement Solution",
                    description="Produce implementation artifacts.",
                    capability="agent.coding",
                    depends_on=["t1_analyze_goal"],
                    priority=8,
                )
            )
            tasks.append(
                DecomposedTask(
                    task_id="t4_validate",
                    title="Validate Result",
                    description="Inspect outputs, run checks, and summarize defects.",
                    capability="agent.reviewer",
                    depends_on=["t3_implement"],
                    priority=8,
                )
            )
        else:
            tasks.append(
                DecomposedTask(
                    task_id="t3_execute",
                    title="Execute Plan",
                    description="Perform multi-step response generation and tool usage.",
                    capability="agent.executor",
                    depends_on=["t1_analyze_goal"],
                    priority=8,
                )
            )
            tasks.append(
                DecomposedTask(
                    task_id="t4_review",
                    title="Review Output",
                    description="Evaluate confidence, consistency, and risk.",
                    capability="agent.reviewer",
                    depends_on=["t3_execute"],
                    priority=8,
                )
            )

        tasks.append(
            DecomposedTask(
                task_id="t5_finalize",
                title="Finalize Response",
                description="Prepare complete final output for the user.",
                capability="agent.executor",
                depends_on=["t4_validate" if any(t.task_id == "t4_validate" for t in tasks) else "t4_review"],
                priority=7,
            )
        )
        return tasks

    @staticmethod
    def _needs_research(lower_text: str) -> bool:
        return bool(
            re.search(
                r"\b(architecture|roadmap|research|compare|investigate|report|design|strategy)\b",
                lower_text,
            )
        )

    @staticmethod
    def _needs_coding(lower_text: str) -> bool:
        return bool(
            re.search(
                r"\b(code|implement|build|refactor|fix|debug|python|c\+\+|javascript|typescript)\b",
                lower_text,
            )
        )

