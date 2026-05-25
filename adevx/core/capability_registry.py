"""Capability registry decouples planning from execution implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import CapabilityExecutor


@dataclass(slots=True)
class CapabilityEntry:
    name: str
    executor: CapabilityExecutor
    metadata: dict[str, Any] = field(default_factory=dict)


class InMemoryCapabilityRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, CapabilityEntry] = {}

    def register(
        self,
        name: str,
        executor: CapabilityExecutor,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        key = name.strip().lower()
        self._entries[key] = CapabilityEntry(
            name=key,
            executor=executor,
            metadata=metadata or {},
        )

    def get(self, name: str) -> CapabilityExecutor | None:
        entry = self._entries.get(name.strip().lower())
        return entry.executor if entry else None

    def metadata(self, name: str) -> dict[str, Any]:
        entry = self._entries.get(name.strip().lower())
        return dict(entry.metadata) if entry else {}

    def list_capabilities(self) -> list[str]:
        return sorted(self._entries.keys())

