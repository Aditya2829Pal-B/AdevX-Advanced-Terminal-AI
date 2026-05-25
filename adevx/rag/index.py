"""Workspace indexing adapter.

This scaffold intentionally delegates to existing taskbot ProjectRAGStore during
migration to avoid regressions while architecture is being modularized.
"""

from __future__ import annotations

import asyncio

import taskbot


class WorkspaceIndexAdapter:
    def __init__(self) -> None:
        self._store = taskbot.ProjectRAGStore()

    async def rebuild(self, chunk_lines: int = 60, overlap_lines: int = 15) -> str:
        return await asyncio.to_thread(
            self._store.rebuild,
            chunk_lines,
            overlap_lines,
        )

    async def status_text(self) -> str:
        return await asyncio.to_thread(self._store.status_text)

    async def set_enabled(self, enabled: bool) -> None:
        await asyncio.to_thread(self._store.set_enabled, enabled)

    async def retrieve_context(self, query: str, top_k: int = 4, max_chars: int = 3500) -> str:
        return await asyncio.to_thread(self._store.retrieve_context, query, top_k, max_chars)

