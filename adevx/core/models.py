"""Core domain models used by all runtime layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4


Role = Literal["system", "developer", "user", "assistant", "tool"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str
    name: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class UserRequest:
    text: str
    mode: str = "chat"
    session_id: str = "default"
    request_id: str = field(default_factory=lambda: new_id("req"))
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class AssistantChunk:
    request_id: str
    text: str
    final: bool = False
    sequence: int = 0


@dataclass(slots=True)
class AssistantResponse:
    request_id: str
    text: str
    provider: str = ""
    mode: str = "chat"
    tool_calls: list["ToolInvocation"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]
    call_id: str = field(default_factory=lambda: new_id("tool"))


@dataclass(slots=True)
class ToolResult:
    call_id: str
    name: str
    output: str
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlannerStep:
    id: str
    title: str
    description: str
    capability: str
    input_payload: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    allow_parallel: bool = False


@dataclass(slots=True)
class ExecutionPlan:
    request_id: str
    steps: list[PlannerStep]
    summary: str = ""


@dataclass(slots=True)
class ProviderOutcome:
    provider: str
    response_text: str
    latency_ms: float
    model: str
    success: bool = True
    error: str = ""


class AgentStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class AgentState:
    agent_id: str
    session_id: str
    status: AgentStatus = AgentStatus.IDLE
    active_request_id: str | None = None
    active_mode: str = "chat"
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class DomainEvent:
    name: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: new_id("evt"))
    correlation_id: str | None = None
    causation_id: str | None = None
    occurred_at: datetime = field(default_factory=utc_now)

