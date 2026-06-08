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

    async def repo_symbols_text(self, limit: int = 120, search: str = "") -> str:
        return await self._index.repo_symbols_text(limit=limit, search=search)

    async def repo_graph_text(self, focus: str = "", max_edges: int = 80) -> str:
        return await self._index.repo_graph_text(focus=focus, max_edges=max_edges)

    async def repo_explain_text(self, symbol: str) -> str:
        return await self._index.repo_explain_text(symbol)

    async def repo_references_text(self, symbol: str, limit: int = 30) -> str:
        return await self._index.repo_references_text(symbol=symbol, limit=limit)

    async def repo_snapshot(self) -> dict[str, object]:
        return await self._index.repo_snapshot()
