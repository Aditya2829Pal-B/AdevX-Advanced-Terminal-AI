"""Provider fallback router with retry and circuit breaker policies."""

from __future__ import annotations

import time
from dataclasses import replace

from adevx.core.errors import CircuitOpenError, ProviderError
from adevx.core.models import AssistantResponse, ChatMessage, ProviderOutcome, UserRequest
from adevx.core.redaction import redact_secrets
from adevx.execution.circuit_breaker import CircuitBreakerGroup
from adevx.execution.retries import RetryPolicy, run_with_retry
from adevx.providers.base import BaseProvider


class ProviderRouter:
    def __init__(
        self,
        providers: dict[str, BaseProvider],
        chain: list[str],
        retry_policy: RetryPolicy,
        circuits: CircuitBreakerGroup,
    ) -> None:
        self._providers = providers
        self._chain = chain
        self._retry_policy = retry_policy
        self._circuits = circuits
        self._last_outcomes: list[ProviderOutcome] = []

    @property
    def last_outcomes(self) -> list[ProviderOutcome]:
        return list(self._last_outcomes)

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
    ) -> AssistantResponse:
        self._last_outcomes = []
        errors: list[str] = []
        attempted = 0

        for provider_name in self._chain:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue
            attempted += 1
            breaker = self._circuits.for_key(provider_name)
            start = time.perf_counter()
            try:
                breaker.before_call()

                async def _call():
                    return await provider.complete(messages=messages, request=request, stream=False)

                retry_policy = replace(
                    self._retry_policy,
                    retry_if=self._retry_policy.retry_if or _is_retryable_provider_error,
                )
                response = await run_with_retry(_call, retry_policy)
                breaker.on_success()
                latency_ms = (time.perf_counter() - start) * 1000.0
                self._last_outcomes.append(
                    ProviderOutcome(
                        provider=provider_name,
                        response_text=response.text,
                        latency_ms=latency_ms,
                        model=provider.model,
                        success=True,
                    )
                )
                return response
            except CircuitOpenError as exc:
                latency_ms = (time.perf_counter() - start) * 1000.0
                message = redact_secrets(f"{provider_name}: {exc}")
                errors.append(message)
                self._last_outcomes.append(
                    ProviderOutcome(
                        provider=provider_name,
                        response_text="",
                        latency_ms=latency_ms,
                        model=provider.model,
                        success=False,
                        error=str(exc),
                    )
                )
            except Exception as exc:
                breaker.on_failure()
                latency_ms = (time.perf_counter() - start) * 1000.0
                message = redact_secrets(f"{provider_name}: {exc}")
                errors.append(message)
                self._last_outcomes.append(
                    ProviderOutcome(
                        provider=provider_name,
                        response_text="",
                        latency_ms=latency_ms,
                        model=provider.model,
                        success=False,
                        error=redact_secrets(exc),
                    )
                )

        if attempted == 0:
            raise ProviderError(
                "No providers are configured for the active chain. "
                "Set provider API keys (OPENAI_API_KEY / OPENROUTER_API_KEY / GROQ_API_KEY / "
                "TOGETHER_API_KEY) or enable local Ollama (ADEVX_ENABLE_OLLAMA=1)."
            )
        raise ProviderError(redact_secrets("All providers failed.\n" + "\n".join(f"- {err}" for err in errors)))


def _is_retryable_provider_error(exc: Exception) -> bool:
    if isinstance(exc, CircuitOpenError):
        return False
    text = str(exc).lower()
    permanent_markers = (
        "invalid header",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "incorrect api key",
        "insufficient_quota",
        "model not found",
        "http error 400",
        "http error 401",
        "http error 403",
        "http error 404",
    )
    if any(marker in text for marker in permanent_markers):
        return False
    return True
