"""Role-based agents for autonomous reasoning loops."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adevx.core.autonomy_models import DecomposedTask, Goal, PlanCandidate, SelectedPlan
from adevx.core.models import ChatMessage, UserRequest
from adevx.execution.tool_selection import ToolSelectionEngine
from adevx.memory.working import LongTermRetriever, ScratchpadMemory, WorkingMemory
from adevx.planning.goal_decomposer import GoalDecomposer
from adevx.planning.tot_planner import TreeOfThoughtPlanner
from adevx.providers.router import ProviderRouter
from adevx.rag.retriever import WorkspaceRetriever
from adevx.tools.registry import ToolRegistry


@dataclass(slots=True)
class PlannerOutput:
    goal: Goal
    selected_plan: SelectedPlan
    candidates: list[PlanCandidate]
    thought_trace: str


@dataclass(slots=True)
class PlannerAgent:
    decomposer: GoalDecomposer
    tot_planner: TreeOfThoughtPlanner
    working_memory: WorkingMemory

    async def plan(self, request: UserRequest) -> PlannerOutput:
        goal = Goal(
            objective=request.text,
            constraints=[f"mode={request.mode}"],
            success_criteria=["complete objective", "maintain correctness", "minimize hallucination risk"],
        )
        tasks = self.decomposer.decompose(goal, preferred_mode=request.mode)
        thoughts, candidates = self.tot_planner.generate_candidates(goal, tasks)
        selected = self.tot_planner.select(candidates)
        self.working_memory.put("current_goal", goal.objective, weight=2.0, metadata={"goal_id": goal.goal_id})
        thought_trace = "\n".join(
            f"- [{th.branch}] score={th.score:.2f}: {th.hypothesis} ({th.rationale})"
            for th in thoughts
        )
        return PlannerOutput(goal=goal, selected_plan=selected, candidates=candidates, thought_trace=thought_trace)


@dataclass(slots=True)
class ResearchAgent:
    retriever: WorkspaceRetriever
    long_term: LongTermRetriever
    working_memory: WorkingMemory

    async def gather(self, request: UserRequest, goal: Goal) -> dict[str, str]:
        rag = await self.retriever.retrieve(goal.objective, top_k=4)
        notes = await self.long_term.retrieve(request.session_id, goal.objective, limit=8)
        prioritized = self.working_memory.render_prioritized(goal.objective, limit=10)
        context = {
            "rag_context": rag,
            "long_term_notes": "\n".join(f"- {n}" for n in notes),
            "working_context": prioritized,
        }
        if rag:
            self.working_memory.put("recent_rag", rag[:900], weight=1.4)
        if notes:
            self.working_memory.put("recent_notes", "; ".join(notes[:4])[:900], weight=1.2)
        return context


@dataclass(slots=True)
class ExecutorAgent:
    provider_router: ProviderRouter
    tool_registry: ToolRegistry
    selector: ToolSelectionEngine
    scratchpad: ScratchpadMemory
    working_memory: WorkingMemory

    async def execute_task(
        self,
        request: UserRequest,
        task: DecomposedTask,
        research_context: dict[str, str],
    ) -> tuple[str, float]:
        self.scratchpad.add("task", f"{task.task_id}: {task.title}")
        if task.capability in {"agent.executor", "agent.coding", "agent.research"}:
            tool_choice = self.selector.choose(task.description, self.tool_registry.list_tools(), task.tool_hints)
            prompt = self._build_prompt(request, task, research_context, tool_choice=tool_choice)
            response = await self.provider_router.complete(
                messages=[
                    ChatMessage(role="developer", content="Use ReAct: think briefly, act, observe, conclude."),
                    ChatMessage(role="developer", content=f"Scratchpad:\n{self.scratchpad.render(limit=15)}"),
                    ChatMessage(role="user", content=prompt),
                ],
                request=request,
            )
            text = response.text
            confidence = self._confidence_from_text(text)
            self.scratchpad.add("observation", text[:500], metadata={"task_id": task.task_id})
            self.working_memory.put(f"task_{task.task_id}", text[:700], weight=1.3)
            return text, confidence

        if task.capability == "agent.reviewer":
            summary = "Review pending execution artifacts and verify consistency."
            self.scratchpad.add("review", summary)
            return summary, 0.7

        return f"Unhandled capability for task {task.task_id}", 0.4

    def _build_prompt(
        self,
        request: UserRequest,
        task: DecomposedTask,
        research_context: dict[str, str],
        tool_choice: str | None,
    ) -> str:
        parts = [
            f"Mode: {request.mode}",
            f"Task: {task.title}",
            f"Task details: {task.description}",
            "Research context:",
            research_context.get("rag_context", ""),
            "Long-term notes:",
            research_context.get("long_term_notes", ""),
            "Working context:",
            research_context.get("working_context", ""),
        ]
        if tool_choice:
            parts.append(f"Suggested tool: {tool_choice}")
        return "\n".join(part for part in parts if part.strip())

    @staticmethod
    def _confidence_from_text(text: str) -> float:
        score = 0.45
        low = text.lower()
        if len(text.strip()) > 100:
            score += 0.15
        if any(token in low for token in ("step", "verify", "result", "therefore")):
            score += 0.15
        if "error" in low or "failed" in low:
            score -= 0.2
        return max(0.0, min(score, 0.98))


@dataclass(slots=True)
class ReviewerAgent:
    async def critique(self, output: str) -> str:
        issues: list[str] = []
        if len(output.strip()) < 20:
            issues.append("output_too_short")
        if "I don't know" in output:
            issues.append("uncertainty_marker")
        if not issues:
            return "review:pass"
        return "review:fail " + ", ".join(issues)


@dataclass(slots=True)
class CodingAgent:
    executor: ExecutorAgent

    async def solve(self, request: UserRequest, task: DecomposedTask, research_context: dict[str, str]) -> tuple[str, float]:
        return await self.executor.execute_task(request, task, research_context)

