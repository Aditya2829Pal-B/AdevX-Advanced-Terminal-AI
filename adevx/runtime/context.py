"""Runtime context bundle for dependency injection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adevx.agents.manager import AgentStateManager
from adevx.core.capability_registry import InMemoryCapabilityRegistry
from adevx.core.config import RuntimeConfig
from adevx.execution.orchestrator import ExecutionOrchestrator
from adevx.runtime.event_bus import AsyncEventBus
from adevx.telemetry.logger import StructuredLogger


@dataclass(slots=True)
class RuntimeContext:
    config: RuntimeConfig
    logger: StructuredLogger
    event_bus: AsyncEventBus
    agent_manager: AgentStateManager
    capabilities: InMemoryCapabilityRegistry
    orchestrator: ExecutionOrchestrator
    planner_agent: Any | None = None
    research_agent: Any | None = None
    executor_agent: Any | None = None
    reviewer_agent: Any | None = None
    memory_agent: Any | None = None
    autonomous_engine: Any | None = None
    provider_router: Any | None = None
    tool_registry: Any | None = None
    memory_store: Any | None = None
    working_memory: Any | None = None
    retriever: Any | None = None
    rag_index: Any | None = None
    metrics: Any | None = None
