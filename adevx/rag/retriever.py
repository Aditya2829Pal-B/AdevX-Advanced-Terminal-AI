"""Retrieval interface over workspace index."""

from __future__ import annotations

from adevx.rag.index import WorkspaceIndexAdapter


class WorkspaceRetriever:
    def __init__(self, index: WorkspaceIndexAdapter) -> None:
        self._index = index

    async def retrieve(self, query: str, top_k: int = 4) -> str:
        return await self._index.retrieve_context(query, top_k=top_k, max_chars=3000)

