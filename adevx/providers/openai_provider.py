"""OpenAI-compatible provider adapter skeleton."""

from __future__ import annotations

from adevx.core.models import AssistantResponse, ChatMessage, UserRequest
from adevx.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        self.name = "openai"
        self.model = model

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
        stream: bool = False,
    ) -> AssistantResponse:
        # Production implementation:
        # 1) map messages to OpenAI format
        # 2) call /chat/completions with retries
        # 3) parse tool calls + response metadata
        # Kept as scaffold to preserve compatibility with current monolith.
        text = f"[OpenAIProvider:{self.model}] {request.text}"
        return AssistantResponse(
            request_id=request.request_id,
            text=text,
            provider=self.name,
            mode=request.mode,
            metadata={"scaffold": True},
        )

