"""Retrieval interface over workspace index."""

from __future__ import annotations

from adevx.rag.index import WorkspaceIndexAdapter


class WorkspaceRetriever:
    def __init__(self, index: WorkspaceIndexAdapter) -> None:
        self._index = index

    async def retrieve(
        self,
        query: str,
        top_k: int = 4,
        max_chars: int = 3000,
    ) -> str:
        return await self._index.retrieve_context(query, top_k=top_k, max_chars=max_chars)

    async def rebuild(self, chunk_lines: int = 80, overlap_lines: int = 20) -> str:
        return await self._index.rebuild(chunk_lines=chunk_lines, overlap_lines=overlap_lines)

    async def status_text(self) -> str:
        return await self._index.status_text()
