"""Default conversation agent implementation."""

from __future__ import annotations

from dataclasses import dataclass

from adevx.agents.base import BaseAgent
from adevx.core.models import AssistantResponse, UserRequest
from adevx.execution.orchestrator import ExecutionOrchestrator
from adevx.runtime.cancellation import CancellationToken


@dataclass(slots=True)
class SessionAgent(BaseAgent):
    agent_id: str
    orchestrator: ExecutionOrchestrator

    async def handle(self, request: UserRequest, cancel_token: CancellationToken) -> AssistantResponse:
        return await self.orchestrator.handle_request(request=request, cancel_token=cancel_token)

