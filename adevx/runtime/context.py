"""Runtime context bundle for dependency injection."""

from __future__ import annotations

from dataclasses import dataclass

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
