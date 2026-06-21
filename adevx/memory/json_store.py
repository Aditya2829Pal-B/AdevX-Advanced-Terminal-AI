"""JSON-backed local-first memory store with layered memory utilities."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adevx.memory.base import MemoryRecord


def _terms(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", text.lower())


def _recency_score(created_at: str) -> float:
    try:
        dt = datetime.fromisoformat(created_at)
    except ValueError:
        return 0.4
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    return max(0.1, 1.0 / (1.0 + age_hours / 24.0))


class JsonMemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, list[MemoryRecord]] = {}
        self._meta: dict[str, Any] = {
            "version": 2,
            "summaries": {},
            "projects": {},
        }
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
            if session_id == "__meta" and isinstance(items, dict):
                self._meta.update(items)
                continue
            if not isinstance(items, list):
                continue
            records: list[MemoryRecord] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {}
                if "kind" not in metadata:
                    metadata["kind"] = "conversation"
                records.append(
                    MemoryRecord(
                        session_id=session_id,
                        text=text,
                        metadata=metadata,
                        created_at=str(item.get("created_at", "")) or MemoryRecord(session_id=session_id, text=text).created_at,
                    )
                )
            self._data[session_id] = records[-400:]

    async def _save(self) -> None:
        serializable: dict[str, Any] = {
            session_id: [
                {"text": record.text, "metadata": record.metadata, "created_at": record.created_at}
                for record in records[-400:]
            ]
            for session_id, records in self._data.items()
        }
        serializable["__meta"] = self._meta
        await asyncio.to_thread(self._write_atomic, serializable)

    def _write_atomic(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    async def add(self, session_id: str, text: str, metadata: dict | None = None) -> None:
        note = text.strip()
        if not note:
            return
        async with self._lock:
            meta = dict(metadata or {})
            meta.setdefault("kind", "conversation")
            meta.setdefault("project", self.path.parent.name)
            items = self._data.setdefault(session_id, [])
            items.append(MemoryRecord(session_id=session_id, text=note, metadata=meta))
            if len(items) > 400:
                del items[0 : len(items) - 400]
            project_name = str(meta.get("project", "")).strip()
            if project_name:
                project_notes = self._meta.setdefault("projects", {}).setdefault(project_name, [])
                if note not in project_notes:
                    project_notes.append(note)
                    if len(project_notes) > 120:
                        del project_notes[0 : len(project_notes) - 120]
            await self._save()

    async def get_recent(self, session_id: str, limit: int = 20) -> list[str]:
        async with self._lock:
            items = self._data.get(session_id, [])
            return [record.text for record in items[-limit:]]

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._data[session_id] = []
            await self._save()

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        question = query.strip()
        if not question:
            return []
        async with self._lock:
            if session_id:
                records = list(self._data.get(session_id, []))
            else:
                records = [record for items in self._data.values() for record in items]
        query_terms = set(_terms(question))
        if not query_terms:
            return []
        scored: list[tuple[float, MemoryRecord]] = []
        for record in records:
            record_terms = set(_terms(record.text))
            overlap = len(query_terms & record_terms)
            if overlap <= 0:
                continue
            kind = str(record.metadata.get("kind", "conversation"))
            kind_boost = {
                "semantic": 0.25,
                "project": 0.22,
                "episodic": 0.16,
                "summary": 0.14,
                "conversation": 0.08,
            }.get(kind, 0.05)
            score = overlap / max(1, len(query_terms))
            score += kind_boost
            score += _recency_score(record.created_at) * 0.3
            scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[: max(1, limit)]]

    async def stats(self, session_id: str | None = None) -> dict[str, Any]:
        async with self._lock:
            if session_id:
                sessions = {session_id: list(self._data.get(session_id, []))}
            else:
                sessions = {key: list(value) for key, value in self._data.items()}
            project_meta = dict(self._meta.get("projects", {})) if isinstance(self._meta.get("projects"), dict) else {}

        total_records = 0
        kind_counts: Counter[str] = Counter()
        project_counts: Counter[str] = Counter()
        session_sizes: dict[str, int] = {}
        for sid, records in sessions.items():
            session_sizes[sid] = len(records)
            total_records += len(records)
            for record in records:
                kind_counts[str(record.metadata.get("kind", "conversation"))] += 1
                project_name = str(record.metadata.get("project", "")).strip()
                if project_name:
                    project_counts[project_name] += 1

        return {
            "sessions": len(sessions),
            "total_records": total_records,
            "kind_counts": dict(kind_counts),
            "project_counts": dict(project_counts),
            "session_sizes": session_sizes,
            "project_memory_entries": {key: len(value) for key, value in project_meta.items() if isinstance(value, list)},
        }

    async def consolidate(self, session_id: str, keep_recent: int = 80) -> dict[str, Any]:
        async with self._lock:
            items = list(self._data.get(session_id, []))
            if not items:
                return {"session_id": session_id, "collapsed": 0, "summary": ""}

            deduped: list[MemoryRecord] = []
            seen: set[str] = set()
            for record in reversed(items):
                key = record.text.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(record)
            deduped.reverse()

            collapsed = max(0, len(deduped) - keep_recent)
            older = deduped[:collapsed]
            recent = deduped[collapsed:]

            summary_text = ""
            if older:
                counter: Counter[str] = Counter()
                for record in older:
                    counter.update(term for term in _terms(record.text) if len(term) >= 4)
                keywords = [term for term, _count in counter.most_common(8)]
                examples = [record.text[:80] for record in older[-3:]]
                parts = ["Session memory consolidation"]
                if keywords:
                    parts.append("topics=" + ", ".join(keywords))
                if examples:
                    parts.append("examples=" + " | ".join(examples))
                summary_text = "; ".join(parts)
                recent.insert(
                    0,
                    MemoryRecord(
                        session_id=session_id,
                        text=summary_text,
                        metadata={
                            "kind": "summary",
                            "source": "consolidation",
                            "collapsed_count": len(older),
                            "project": self.path.parent.name,
                        },
                    ),
                )

            self._data[session_id] = recent[-400:]
            summaries = self._meta.setdefault("summaries", {})
            if summary_text:
                summaries[session_id] = summary_text
            await self._save()
            return {
                "session_id": session_id,
                "collapsed": len(older),
                "retained": len(self._data[session_id]),
                "summary": summary_text,
            }
