"""Agent definitions and state manager."""

from __future__ import annotations

__all__ = [
    "AgentStateManager",
    "CollaborationManager",
    "PlannerAgent",
    "ExecutionAgent",
    "ExecutorAgent",
    "ReviewAgent",
    "ReviewerAgent",
    "ResearchAgent",
    "CodingAgent",
    "MemoryAgent",
]


def __getattr__(name: str):
    if name == "AgentStateManager":
        from .manager import AgentStateManager

        return AgentStateManager
    if name == "CollaborationManager":
        from .collaboration import CollaborationManager

        return CollaborationManager
    if name in {
        "PlannerAgent",
        "ExecutionAgent",
        "ExecutorAgent",
        "ReviewAgent",
        "ReviewerAgent",
        "ResearchAgent",
        "CodingAgent",
        "MemoryAgent",
    }:
        from .roles import (
            CodingAgent,
            ExecutionAgent,
            ExecutorAgent,
            MemoryAgent,
            PlannerAgent,
            ResearchAgent,
            ReviewAgent,
            ReviewerAgent,
        )

        mapping = {
            "PlannerAgent": PlannerAgent,
            "ExecutionAgent": ExecutionAgent,
            "ExecutorAgent": ExecutorAgent,
            "ReviewAgent": ReviewAgent,
            "ReviewerAgent": ReviewerAgent,
            "ResearchAgent": ResearchAgent,
            "CodingAgent": CodingAgent,
            "MemoryAgent": MemoryAgent,
        }
        return mapping[name]
    raise AttributeError(name)
