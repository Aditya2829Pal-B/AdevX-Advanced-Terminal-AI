"""JSON-backed local-first memory store."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from adevx.memory.base import MemoryRecord


class JsonMemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, list[MemoryRecord]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        for session_id, items in raw.items():
            if not isinstance(items, list):
                continue
            records: list[MemoryRecord] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                records.append(
                    MemoryRecord(
                        session_id=session_id,
                        text=text,
                        metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {},
                        created_at=str(item.get("created_at", "")) or MemoryRecord(session_id=session_id, text=text).created_at,
                    )
                )
            self._data[session_id] = records[-400:]

    async def _save(self) -> None:
        serializable = {
            session_id: [
                {"text": r.text, "metadata": r.metadata, "created_at": r.created_at}
                for r in records[-400:]
            ]
            for session_id, records in self._data.items()
        }
        await asyncio.to_thread(
            self.path.write_text,
            json.dumps(serializable, indent=2),
            "utf-8",
        )

    async def add(self, session_id: str, text: str, metadata: dict | None = None) -> None:
        note = text.strip()
        if not note:
            return
        async with self._lock:
            items = self._data.setdefault(session_id, [])
            items.append(MemoryRecord(session_id=session_id, text=note, metadata=metadata or {}))
            if len(items) > 400:
                del items[0 : len(items) - 400]
            await self._save()

    async def get_recent(self, session_id: str, limit: int = 20) -> list[str]:
        async with self._lock:
            items = self._data.get(session_id, [])
            return [r.text for r in items[-limit:]]

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._data[session_id] = []
            await self._save()

