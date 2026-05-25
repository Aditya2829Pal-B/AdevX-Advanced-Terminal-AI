"""Autonomous reasoning domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    EXECUTING = "executing"
    REVISED = "revised"
    COMPLETED = "completed"
    FAILED = "failed"


class NodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReviewAction(str, Enum):
    ACCEPT = "accept"
    RETRY = "retry"
    REPLAN = "replan"
    HALT = "halt"


@dataclass(slots=True)
class Goal:
    objective: str
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    goal_id: str = field(default_factory=lambda: _id("goal"))
    created_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DecomposedTask:
    task_id: str
    title: str
    description: str
    capability: str
    tool_hints: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    priority: int = 5
    parallel_group: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanCandidate:
    plan_id: str
    summary: str
    tasks: list[DecomposedTask]
    strategy: str
    confidence: float
    reasoning: str
    estimated_tokens: int


@dataclass(slots=True)
class ThoughtNode:
    thought_id: str
    branch: str
    hypothesis: str
    score: float
    rationale: str


@dataclass(slots=True)
class SelectedPlan:
    candidate: PlanCandidate
    status: PlanStatus = PlanStatus.READY
    selected_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class ExecutionNode:
    node_id: str
    title: str
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    max_attempts: int = 2
    output: str = ""
    error: str = ""
    confidence: float = 0.0
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class ReflectionReport:
    node_id: str
    confidence: float
    hallucination_risk: float
    issues: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    action: ReviewAction = ReviewAction.ACCEPT
    revised_payload: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(slots=True)
class Checkpoint:
    checkpoint_id: str
    request_id: str
    step_index: int
    snapshot: dict[str, Any]
    created_at: datetime = field(default_factory=_now)

