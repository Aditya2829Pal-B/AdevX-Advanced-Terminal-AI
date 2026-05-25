"""Typed exception hierarchy for AdevX runtime."""

from __future__ import annotations


class AdevXError(Exception):
    """Base class for all application-specific runtime errors."""


class ConfigurationError(AdevXError):
    """Raised when required configuration is invalid or missing."""


class ProviderError(AdevXError):
    """Raised when provider requests fail."""


class ToolExecutionError(AdevXError):
    """Raised when a tool invocation fails."""


class PlanningError(AdevXError):
    """Raised when plan generation fails."""


class ExecutionError(AdevXError):
    """Raised when plan execution fails."""


class CancelledError(AdevXError):
    """Raised when an operation is cancelled by a token."""


class CircuitOpenError(AdevXError):
    """Raised when a circuit breaker blocks a provider call."""

