"""Circuit breaker for provider reliability control."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from adevx.core.errors import CircuitOpenError


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitBreaker:
    fail_threshold: int = 3
    recovery_seconds: float = 10.0
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    opened_at: float = 0.0

    def before_call(self) -> None:
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.opened_at
            if elapsed >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError("Circuit is open; call blocked.")

    def on_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.opened_at = 0.0

    def on_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.fail_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()


class CircuitBreakerGroup:
    def __init__(self, fail_threshold: int = 3, recovery_seconds: float = 10.0) -> None:
        self._fail_threshold = fail_threshold
        self._recovery_seconds = recovery_seconds
        self._breakers: dict[str, CircuitBreaker] = {}

    def for_key(self, key: str) -> CircuitBreaker:
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(
                fail_threshold=self._fail_threshold,
                recovery_seconds=self._recovery_seconds,
            )
        return self._breakers[key]

