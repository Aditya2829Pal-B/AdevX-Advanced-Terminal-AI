"""Shared interfaces across architecture layers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol, runtime_checkable

from .models import (
    AssistantResponse,
    ChatMessage,
    DomainEvent,
    ExecutionPlan,
    ToolInvocation,
    ToolResult,
    UserRequest,
)


@runtime_checkable
class EventBus(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def publish(self, event: DomainEvent) -> None: ...

    def subscribe(
        self,
        event_name: str,
        handler: Callable[[DomainEvent], Any],
    ) -> None: ...


@runtime_checkable
class ChatProvider(Protocol):
    name: str
    model: str

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
        stream: bool = False,
    ) -> AssistantResponse: ...

    async def stream_complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class Planner(Protocol):
    async def build_plan(self, request: UserRequest, context: dict[str, Any]) -> ExecutionPlan: ...


@runtime_checkable
class CapabilityExecutor(Protocol):
    name: str

    async def execute(self, step_input: dict[str, Any], request: UserRequest) -> str: ...


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    async def run(self, invocation: ToolInvocation) -> ToolResult: ...


@runtime_checkable
class MemoryStore(Protocol):
    async def add(self, session_id: str, text: str, metadata: dict[str, Any] | None = None) -> None: ...

    async def get_recent(self, session_id: str, limit: int = 20) -> list[str]: ...

    async def clear(self, session_id: str) -> None: ...


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(self, query: str, top_k: int = 4) -> str: ...


@runtime_checkable
class Plugin(Protocol):
    plugin_id: str
    version: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def register(self, registry: "CapabilityRegistry") -> None: ...


@runtime_checkable
class TelemetrySink(Protocol):
    async def emit(self, metric: str, value: float, tags: dict[str, str] | None = None) -> None: ...

    async def log_event(self, event: DomainEvent) -> None: ...


@runtime_checkable
class CapabilityRegistry(Protocol):
    def register(self, name: str, executor: CapabilityExecutor, metadata: dict[str, Any] | None = None) -> None: ...

    def get(self, name: str) -> CapabilityExecutor | None: ...

    def list_capabilities(self) -> list[str]: ...

