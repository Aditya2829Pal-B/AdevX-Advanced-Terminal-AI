"""Cancellation tokens for cooperative async cancellation."""

from __future__ import annotations

import asyncio

from adevx.core.errors import CancelledError


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise CancelledError("Operation cancelled.")

