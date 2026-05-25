"""Streaming renderer abstractions for CLI and future GUI."""

from __future__ import annotations

from collections.abc import AsyncIterator


class StreamRenderer:
    async def render(self, chunks: AsyncIterator[str]) -> str:
        parts: list[str] = []
        async for chunk in chunks:
            print(chunk, end="", flush=True)
            parts.append(chunk)
        print()
        return "".join(parts)

