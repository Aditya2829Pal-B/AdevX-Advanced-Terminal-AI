"""Provider base classes and common utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from adevx.core.models import AssistantResponse, ChatMessage, UserRequest


class BaseProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
        stream: bool = False,
    ) -> AssistantResponse:
        raise NotImplementedError

    async def stream_complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
    ) -> AsyncIterator[str]:
        response = await self.complete(messages=messages, request=request, stream=False)
        yield response.text

