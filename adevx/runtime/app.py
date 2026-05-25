"""AdevX modular runtime facade."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

from adevx.core.config import RuntimeConfig
from adevx.core.models import AssistantResponse, DomainEvent, UserRequest
from adevx.plugins.registry import PluginRegistry
from adevx.runtime.bootstrap import build_runtime_context
from adevx.runtime.cancellation import CancellationToken
from adevx.runtime.context import RuntimeContext
from adevx.runtime.workers import BackgroundWorkerSupervisor
from adevx.core.models import AgentStatus


@dataclass(slots=True)
class AdevXRuntime:
    config: RuntimeConfig
    context: RuntimeContext
    workers: BackgroundWorkerSupervisor
    plugins: PluginRegistry
    _started: bool = False

    @classmethod
    def create(cls, config: RuntimeConfig | None = None) -> "AdevXRuntime":
        cfg = config or RuntimeConfig.from_env()
        context, workers, plugins = build_runtime_context(cfg)
        return cls(config=cfg, context=context, workers=workers, plugins=plugins)

    async def start(self) -> None:
        if self._started:
            return
        await self.context.event_bus.start()
        await self.plugins.start_all()
        await self.workers.start()
        await self.context.event_bus.publish(
            DomainEvent(
                name="runtime.started",
                payload={
                    "workspace": str(self.config.workspace_root),
                    "mode": self.config.default_mode,
                },
            )
        )
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await self.context.event_bus.publish(DomainEvent(name="runtime.stopping", payload={}))
        await self.workers.stop()
        await self.plugins.stop_all()
        await self.context.event_bus.stop()
        self._started = False

    async def handle(self, request: UserRequest, cancel_token: CancellationToken | None = None) -> AssistantResponse:
        if not self._started:
            await self.start()
        token = cancel_token or CancellationToken()
        await self.context.agent_manager.ensure(agent_id="primary", session_id=request.session_id)
        async with self._agent_slot():
            await self.context.agent_manager.update_status(
                agent_id="primary",
                status=AgentStatus.EXECUTING,
                request_id=request.request_id,
            )
            try:
                response = await self.context.orchestrator.handle_request(
                    request=request,
                    cancel_token=token,
                )
                await self.context.agent_manager.update_status(
                    agent_id="primary",
                    status=AgentStatus.COMPLETED,
                    request_id=request.request_id,
                )
                return response
            except Exception:
                await self.context.agent_manager.update_status(
                    agent_id="primary",
                    status=AgentStatus.FAILED,
                    request_id=request.request_id,
                )
                raise

    async def run_once(self, text: str, session_id: str = "default") -> AssistantResponse:
        request = UserRequest(text=text, mode=self.config.default_mode, session_id=session_id)
        return await self.handle(request)

    async def __aenter__(self) -> "AdevXRuntime":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    @asynccontextmanager
    async def _agent_slot(self):
        sem = self.context.agent_manager.semaphore()
        async with sem:
            yield
