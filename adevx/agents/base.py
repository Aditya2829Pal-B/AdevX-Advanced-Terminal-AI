"""Base agent abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from adevx.core.models import AssistantResponse, UserRequest
from adevx.runtime.cancellation import CancellationToken


class BaseAgent(ABC):
    agent_id: str

    @abstractmethod
    async def handle(self, request: UserRequest, cancel_token: CancellationToken) -> AssistantResponse:
        raise NotImplementedError

