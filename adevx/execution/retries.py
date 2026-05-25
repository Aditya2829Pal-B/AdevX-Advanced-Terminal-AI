"""Retry policies with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 4.0
    jitter_ratio: float = 0.2

    def delay_for_attempt(self, attempt: int) -> float:
        raw = min(self.max_delay_s, self.base_delay_s * (2 ** max(0, attempt - 1)))
        jitter = raw * self.jitter_ratio
        return max(0.0, raw + random.uniform(-jitter, jitter))


async def run_with_retry(coro_factory, policy: RetryPolicy) -> T:
    last_error: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_error = exc
            if attempt >= policy.max_attempts:
                break
            await asyncio.sleep(policy.delay_for_attempt(attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Retry failed with no captured error.")

