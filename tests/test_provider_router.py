from __future__ import annotations

import unittest

from adevx.core.errors import ProviderError
from adevx.core.models import AssistantResponse, ChatMessage, UserRequest
from adevx.execution.circuit_breaker import CircuitBreakerGroup
from adevx.execution.retries import RetryPolicy
from adevx.providers.base import BaseProvider
from adevx.providers.router import ProviderRouter


class _OkProvider(BaseProvider):
    def __init__(self, name: str, model: str = "test-model") -> None:
        self.name = name
        self.model = model

    async def complete(self, *, messages: list[ChatMessage], request: UserRequest, stream: bool = False) -> AssistantResponse:
        return AssistantResponse(
            request_id=request.request_id,
            text=f"{self.name}:ok",
            provider=self.name,
            mode=request.mode,
        )


class ProviderRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_raises_if_no_providers_configured(self) -> None:
        router = ProviderRouter(
            providers={},
            chain=["openai"],
            retry_policy=RetryPolicy(max_attempts=1),
            circuits=CircuitBreakerGroup(),
        )
        req = UserRequest(text="hello")
        with self.assertRaises(ProviderError) as ctx:
            await router.complete(messages=[ChatMessage(role="user", content="hello")], request=req)
        self.assertIn("No providers are configured", str(ctx.exception))

    async def test_router_returns_first_success(self) -> None:
        router = ProviderRouter(
            providers={"openai": _OkProvider("openai")},
            chain=["openai"],
            retry_policy=RetryPolicy(max_attempts=1),
            circuits=CircuitBreakerGroup(),
        )
        req = UserRequest(text="hello")
        resp = await router.complete(messages=[ChatMessage(role="user", content="hello")], request=req)
        self.assertEqual(resp.text, "openai:ok")
        self.assertEqual(resp.provider, "openai")


if __name__ == "__main__":
    unittest.main()

