"""Ollama local provider adapter skeleton."""

from __future__ import annotations

from adevx.core.models import AssistantResponse, ChatMessage, UserRequest
from adevx.providers.base import BaseProvider


class OllamaLocalProvider(BaseProvider):
    def __init__(self, model: str = "qwen2.5:7b") -> None:
        self.name = "ollama-local"
        self.model = model

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
        stream: bool = False,
    ) -> AssistantResponse:
        text = f"[OllamaLocalProvider:{self.model}] {request.text}"
        return AssistantResponse(
            request_id=request.request_id,
            text=text,
            provider=self.name,
            mode=request.mode,
            metadata={"scaffold": True, "local_first": True},
        )

