"""Scratchpad and working-memory support for autonomous reasoning."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from adevx.memory.json_store import JsonMemoryStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ScratchpadEntry:
    role: str
    content: str
    created_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)


class ScratchpadMemory:
    def __init__(self, max_entries: int = 300) -> None:
        self.max_entries = max_entries
        self._entries: list[ScratchpadEntry] = []

    def add(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        text = content.strip()
        if not text:
            return
        self._entries.append(
            ScratchpadEntry(
                role=role,
                content=text,
                metadata=metadata or {},
            )
        )
        if len(self._entries) > self.max_entries:
            del self._entries[0 : len(self._entries) - self.max_entries]

    def tail(self, limit: int = 20) -> list[ScratchpadEntry]:
        return self._entries[-limit:]

    def render(self, limit: int = 20) -> str:
        lines: list[str] = []
        for entry in self.tail(limit):
            lines.append(f"[{entry.role}] {entry.content}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._entries.clear()


@dataclass(slots=True)
class WorkingMemoryItem:
    key: str
    value: str
    weight: float = 1.0
    updated_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkingMemory:
    def __init__(self, max_items: int = 120) -> None:
        self.max_items = max_items
        self._items: dict[str, WorkingMemoryItem] = {}

    def put(self, key: str, value: str, weight: float = 1.0, metadata: dict[str, Any] | None = None) -> None:
        k = key.strip().lower()
        if not k:
            return
        self._items[k] = WorkingMemoryItem(
            key=k,
            value=value.strip(),
            weight=max(0.1, min(weight, 5.0)),
            metadata=metadata or {},
        )
        if len(self._items) > self.max_items:
            # Drop least-weighted item.
            drop_key = sorted(
                self._items.values(),
                key=lambda item: (item.weight, item.updated_at),
            )[0].key
            self._items.pop(drop_key, None)

    def get(self, key: str) -> WorkingMemoryItem | None:
        return self._items.get(key.strip().lower())

    def prioritize(self, query: str, limit: int = 12) -> list[WorkingMemoryItem]:
        terms = _terms(query)
        scored: list[tuple[float, WorkingMemoryItem]] = []
        for item in self._items.values():
            base = item.weight
            overlap = len(set(_terms(item.value)) & set(terms))
            age_factor = max(0.1, 1.0 / (1 + (datetime.now(timezone.utc) - item.updated_at).total_seconds() / 3600))
            score = base + overlap * 1.5 + age_factor
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def render_prioritized(self, query: str, limit: int = 12) -> str:
        items = self.prioritize(query, limit=limit)
        if not items:
            return ""
        return "\n".join(f"- ({item.weight:.1f}) {item.key}: {item.value}" for item in items)


class LongTermRetriever:
    """Retrieves best matching session notes from persistent memory."""

    def __init__(self, store: JsonMemoryStore) -> None:
        self.store = store

    async def retrieve(self, session_id: str, query: str, limit: int = 10) -> list[str]:
        notes = await self.store.get_recent(session_id, limit=200)
        if not notes:
            return []
        q_terms = set(_terms(query))
        scored: list[tuple[float, str]] = []
        for note in notes:
            n_terms = set(_terms(note))
            overlap = len(q_terms & n_terms)
            if overlap <= 0:
                continue
            score = overlap / max(1, len(q_terms))
            scored.append((score, note))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [note for _, note in scored[:limit]]


def _terms(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", text.lower())

