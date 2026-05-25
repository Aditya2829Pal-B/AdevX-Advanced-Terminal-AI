"""Agent state manager and multi-agent concurrency controls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from adevx.core.models import AgentState, AgentStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class AgentEnvelope:
    state: AgentState
    lock: asyncio.Lock


class AgentStateManager:
    def __init__(self, max_agents: int = 4) -> None:
        self._agents: dict[str, AgentEnvelope] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_agents)

    async def ensure(self, agent_id: str, session_id: str) -> AgentState:
        async with self._lock:
            env = self._agents.get(agent_id)
            if env is None:
                env = AgentEnvelope(
                    state=AgentState(agent_id=agent_id, session_id=session_id),
                    lock=asyncio.Lock(),
                )
                self._agents[agent_id] = env
            return env.state

    async def update_status(self, agent_id: str, status: AgentStatus, request_id: str | None = None) -> None:
        async with self._lock:
            env = self._agents.get(agent_id)
            if env is None:
                return
            env.state.status = status
            env.state.active_request_id = request_id
            env.state.updated_at = utc_now()

    async def snapshot(self) -> list[AgentState]:
        async with self._lock:
            return [env.state for env in self._agents.values()]

    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

