"""Generic OpenAI-compatible provider scaffold for Groq/OpenRouter/Together."""

from __future__ import annotations

from adevx.core.models import AssistantResponse, ChatMessage, UserRequest
from adevx.providers.base import BaseProvider


class OpenAICompatProvider(BaseProvider):
    def __init__(self, provider_name: str, model: str) -> None:
        self.name = provider_name
        self.model = model

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
        stream: bool = False,
    ) -> AssistantResponse:
        text = f"[{self.name}:{self.model}] {request.text}"
        return AssistantResponse(
            request_id=request.request_id,
            text=text,
            provider=self.name,
            mode=request.mode,
            metadata={"scaffold": True},
        )

