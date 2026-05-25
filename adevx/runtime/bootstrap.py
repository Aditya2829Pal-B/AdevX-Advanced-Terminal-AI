"""Dependency wiring and boot sequence for modular runtime."""

from __future__ import annotations

from pathlib import Path

from adevx.agents.collaboration import CollaborationManager
from adevx.agents.manager import AgentStateManager
from adevx.agents.roles import CodingAgent, ExecutorAgent, PlannerAgent, ResearchAgent, ReviewerAgent
from adevx.core.capability_registry import InMemoryCapabilityRegistry
from adevx.core.config import RuntimeConfig
from adevx.execution.capabilities import (
    AutonomousCapability,
    ClassifierCapability,
    CodingCapability,
    ProviderChatCapability,
    ToolTaskCapability,
    VerifyCapability,
)
from adevx.execution.autonomous_engine import AutonomousReasoningEngine
from adevx.execution.checkpoint_store import CheckpointStore
from adevx.execution.circuit_breaker import CircuitBreakerGroup
from adevx.execution.orchestrator import ExecutionOrchestrator, OrchestratorDependencies
from adevx.execution.pipeline import StepPipelineExecutor
from adevx.execution.reflection import ReflectionEngine
from adevx.execution.retries import RetryPolicy
from adevx.execution.tool_selection import ToolSelectionEngine
from adevx.memory.json_store import JsonMemoryStore
from adevx.memory.working import LongTermRetriever, ScratchpadMemory, WorkingMemory
from adevx.planning.goal_decomposer import GoalDecomposer
from adevx.plugins.registry import PluginRegistry
from adevx.providers.compat_provider import OpenAICompatProvider
from adevx.providers.ollama_provider import OllamaLocalProvider
from adevx.providers.openai_provider import OpenAIProvider
from adevx.providers.router import ProviderRouter
from adevx.rag.index import WorkspaceIndexAdapter
from adevx.rag.retriever import WorkspaceRetriever
from adevx.runtime.context import RuntimeContext
from adevx.runtime.event_bus import AsyncEventBus
from adevx.runtime.workers import BackgroundWorkerSupervisor
from adevx.safety.shell_guard import ShellGuard
from adevx.telemetry.logger import StructuredLogger
from adevx.telemetry.metrics import InMemoryMetrics
from adevx.tools.builtin_tools import build_default_tools
from adevx.tools.registry import ToolRegistry
from adevx.planning.planner import HeuristicPlanner
from adevx.planning.tot_planner import TreeOfThoughtPlanner


def build_runtime_context(config: RuntimeConfig) -> tuple[RuntimeContext, BackgroundWorkerSupervisor, PluginRegistry]:
    logger = StructuredLogger(level=config.log_level)
    event_bus = AsyncEventBus(queue_max_size=config.queue_max_size)
    metrics = InMemoryMetrics()
    event_bus.subscribe("*", metrics.log_event)
    event_bus.subscribe(
        "*",
        lambda evt: logger.debug(
            "event_bus.dispatch",
            event_name=evt.name,
            correlation_id=evt.correlation_id or "",
        ),
    )

    memory_path = Path(config.workspace_root) / ".adevx_memory_modular.json"
    memory = JsonMemoryStore(memory_path)
    scratchpad = ScratchpadMemory(max_entries=500)
    working_memory = WorkingMemory(max_items=180)
    long_term = LongTermRetriever(memory)
    rag_index = WorkspaceIndexAdapter()
    retriever = WorkspaceRetriever(rag_index)

    tool_registry = ToolRegistry()
    guard = ShellGuard(require_approval=True)
    for tool in build_default_tools(guard):
        tool_registry.register(tool)

    providers = {
        "openai": OpenAIProvider(model="gpt-4.1-mini"),
        "groq": OpenAICompatProvider("groq", model="openai/gpt-oss-20b"),
        "openrouter": OpenAICompatProvider("openrouter", model="openrouter/free"),
        "together": OpenAICompatProvider("together", model="openai/gpt-oss-20b"),
        "ollama-local": OllamaLocalProvider(model="qwen2.5:7b"),
    }
    provider_router = ProviderRouter(
        providers=providers,
        chain=list(config.provider_chain),
        retry_policy=RetryPolicy(
            max_attempts=config.max_retries + 1,
            base_delay_s=config.retry_base_delay_s,
            max_delay_s=config.retry_max_delay_s,
        ),
        circuits=CircuitBreakerGroup(
            fail_threshold=config.circuit_fail_threshold,
            recovery_seconds=config.circuit_recovery_s,
        ),
    )

    planner_agent = PlannerAgent(
        decomposer=GoalDecomposer(),
        tot_planner=TreeOfThoughtPlanner(),
        working_memory=working_memory,
    )
    research_agent = ResearchAgent(
        retriever=retriever,
        long_term=long_term,
        working_memory=working_memory,
    )
    executor_agent = ExecutorAgent(
        provider_router=provider_router,
        tool_registry=tool_registry,
        selector=ToolSelectionEngine(),
        scratchpad=scratchpad,
        working_memory=working_memory,
    )
    reviewer_agent = ReviewerAgent()
    coding_agent = CodingAgent(executor=executor_agent)
    collaboration = CollaborationManager(
        planner=planner_agent,
        executor=executor_agent,
        reviewer=reviewer_agent,
        researcher=research_agent,
        coder=coding_agent,
    )
    autonomous_engine = AutonomousReasoningEngine(
        collaboration=collaboration,
        reflection=ReflectionEngine(),
        checkpoints=CheckpointStore(),
        scratchpad=scratchpad,
        working_memory=working_memory,
        event_bus=event_bus,
        logger=logger,
        max_iterations=30,
        max_parallel=3,
    )

    capabilities = InMemoryCapabilityRegistry()
    capabilities.register("capability.classifier", ClassifierCapability())
    capabilities.register(
        "capability.chat",
        ProviderChatCapability(provider_router, memory, retriever),
    )
    capabilities.register(
        "capability.coding",
        CodingCapability(provider_router, memory, retriever),
    )
    capabilities.register("capability.autonomous", AutonomousCapability(autonomous_engine))
    capabilities.register("capability.tools", ToolTaskCapability(tool_registry))
    capabilities.register("capability.verify", VerifyCapability())

    planner = HeuristicPlanner()
    pipeline = StepPipelineExecutor(capabilities)
    agent_manager = AgentStateManager(max_agents=config.max_concurrent_agents)
    orchestrator = ExecutionOrchestrator(
        OrchestratorDependencies(
            planner=planner,
            pipeline=pipeline,
            event_bus=event_bus,
        )
    )

    supervisor = BackgroundWorkerSupervisor()
    plugin_registry = PluginRegistry()

    ctx = RuntimeContext(
        config=config,
        logger=logger,
        event_bus=event_bus,
        agent_manager=agent_manager,
        capabilities=capabilities,
        orchestrator=orchestrator,
    )
    return ctx, supervisor, plugin_registry
