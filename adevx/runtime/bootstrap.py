"""Dependency wiring and boot sequence for modular runtime."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from adevx.agents.collaboration import CollaborationManager
from adevx.agents.manager import AgentStateManager
from adevx.agents.roles import (
    CodingAgent,
    ExecutionAgent,
    MemoryAgent,
    PlannerAgent,
    ResearchAgent,
    ReviewAgent,
)
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
from adevx.providers.base import BaseProvider
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


def _clean_env_secret(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _flag_enabled(name: str, default: str = "1") -> bool:
    raw = os.environ.get(name, default).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _pick_model(default_model: str, specific_env: str) -> str:
    return (
        os.environ.get(specific_env, "").strip()
        or os.environ.get("ADEVX_MODEL", "").strip()
        or default_model
    )


def _build_provider_map(logger: StructuredLogger) -> dict[str, BaseProvider]:
    providers: dict[str, BaseProvider] = {}

    openai_key = _clean_env_secret(os.environ.get("OPENAI_API_KEY"))
    if openai_key:
        providers["openai"] = OpenAIProvider(
            model=_pick_model("gpt-4.1-mini", "ADEVX_OPENAI_MODEL"),
            api_key=openai_key,
            api_base=os.environ.get("ADEVX_OPENAI_BASE", "").strip() or None,
        )
    else:
        logger.info("provider.disabled", provider="openai", reason="missing OPENAI_API_KEY")

    openrouter_key = _clean_env_secret(os.environ.get("OPENROUTER_API_KEY"))
    if openrouter_key:
        providers["openrouter"] = OpenAICompatProvider(
            "openrouter",
            model=_pick_model("openrouter/free", "ADEVX_OPENROUTER_MODEL"),
            api_key=openrouter_key,
            api_base=os.environ.get("ADEVX_OPENROUTER_BASE", "").strip() or None,
        )
    else:
        logger.info("provider.disabled", provider="openrouter", reason="missing OPENROUTER_API_KEY")

    groq_key = _clean_env_secret(os.environ.get("GROQ_API_KEY"))
    if groq_key:
        providers["groq"] = OpenAICompatProvider(
            "groq",
            model=_pick_model("openai/gpt-oss-20b", "ADEVX_GROQ_MODEL"),
            api_key=groq_key,
            api_base=os.environ.get("ADEVX_GROQ_BASE", "").strip() or None,
        )
    else:
        logger.info("provider.disabled", provider="groq", reason="missing GROQ_API_KEY")

    together_key = _clean_env_secret(os.environ.get("TOGETHER_API_KEY"))
    if together_key:
        providers["together"] = OpenAICompatProvider(
            "together",
            model=_pick_model("openai/gpt-oss-20b", "ADEVX_TOGETHER_MODEL"),
            api_key=together_key,
            api_base=os.environ.get("ADEVX_TOGETHER_BASE", "").strip() or None,
        )
    else:
        logger.info("provider.disabled", provider="together", reason="missing TOGETHER_API_KEY")

    if _flag_enabled("ADEVX_ENABLE_OLLAMA", "1"):
        providers["ollama-local"] = OllamaLocalProvider(
            model=_pick_model("qwen2.5:7b", "ADEVX_OLLAMA_MODEL"),
            api_base=os.environ.get("ADEVX_OLLAMA_BASE", "").strip() or None,
            api_key=os.environ.get("ADEVX_OLLAMA_API_KEY", "").strip() or None,
        )
    else:
        logger.info("provider.disabled", provider="ollama-local", reason="ADEVX_ENABLE_OLLAMA=0")

    logger.info(
        "providers.initialized",
        total=len(providers),
        names=",".join(sorted(providers.keys())),
    )
    return providers


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
    rag_index = WorkspaceIndexAdapter(workspace_root=Path(config.workspace_root))
    retriever = WorkspaceRetriever(rag_index)

    tool_registry = ToolRegistry()
    guard = ShellGuard(require_approval=True)
    for tool in build_default_tools(guard):
        tool_registry.register(tool)

    providers = _build_provider_map(logger)
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
    executor_agent = ExecutionAgent(
        provider_router=provider_router,
        tool_registry=tool_registry,
        selector=ToolSelectionEngine(),
        scratchpad=scratchpad,
        working_memory=working_memory,
    )
    reviewer_agent = ReviewAgent()
    memory_agent = MemoryAgent(long_term=long_term, working_memory=working_memory)
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
    refresh_every_s = max(5.0, float(os.environ.get("ADEVX_RAG_BACKGROUND_REFRESH_S", "30")))

    async def _rag_refresh_worker() -> None:
        while True:
            await asyncio.sleep(refresh_every_s)
            try:
                result = await rag_index.refresh()
                logger.debug("rag.refresh", result=result)
            except Exception as exc:
                logger.warning("rag.refresh.failed", error=str(exc))

    supervisor.register("rag-refresh", _rag_refresh_worker)
    plugin_registry = PluginRegistry()

    ctx = RuntimeContext(
        config=config,
        logger=logger,
        event_bus=event_bus,
        agent_manager=agent_manager,
        capabilities=capabilities,
        orchestrator=orchestrator,
        planner_agent=planner_agent,
        research_agent=research_agent,
        executor_agent=executor_agent,
        reviewer_agent=reviewer_agent,
        memory_agent=memory_agent,
        autonomous_engine=autonomous_engine,
        provider_router=provider_router,
        tool_registry=tool_registry,
        memory_store=memory,
        working_memory=working_memory,
        retriever=retriever,
        rag_index=rag_index,
        metrics=metrics,
    )
    return ctx, supervisor, plugin_registry
