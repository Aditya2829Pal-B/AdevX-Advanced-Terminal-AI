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


class _FailProvider(BaseProvider):
    def __init__(self, name: str, error: Exception, model: str = "test-model") -> None:
        self.name = name
        self.model = model
        self.error = error
        self.calls = 0

    async def complete(self, *, messages: list[ChatMessage], request: UserRequest, stream: bool = False) -> AssistantResponse:
        self.calls += 1
        raise self.error


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

    async def test_router_does_not_retry_permanent_auth_errors_and_redacts(self) -> None:
        provider = _FailProvider("openai", ProviderError("HTTP error 401: Bearer sk-proj-secret123456789"))
        router = ProviderRouter(
            providers={"openai": provider},
            chain=["openai"],
            retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0),
            circuits=CircuitBreakerGroup(),
        )
        req = UserRequest(text="hello")
        with self.assertRaises(ProviderError) as ctx:
            await router.complete(messages=[ChatMessage(role="user", content="hello")], request=req)
        self.assertEqual(provider.calls, 1)
        self.assertNotIn("sk-proj-secret", str(ctx.exception))
        self.assertIn("[REDACTED]", str(ctx.exception))

    async def test_router_falls_back_after_transient_failure(self) -> None:
        failing = _FailProvider("openai", ProviderError("temporary timeout"))
        ok = _OkProvider("groq")
        router = ProviderRouter(
            providers={"openai": failing, "groq": ok},
            chain=["openai", "groq"],
            retry_policy=RetryPolicy(max_attempts=1, base_delay_s=0),
            circuits=CircuitBreakerGroup(),
        )
        req = UserRequest(text="hello")
        resp = await router.complete(messages=[ChatMessage(role="user", content="hello")], request=req)
        self.assertEqual(resp.text, "groq:ok")


if __name__ == "__main__":
    unittest.main()
