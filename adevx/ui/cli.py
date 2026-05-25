"""CLI facade over modular runtime."""

from __future__ import annotations

import asyncio

from adevx.core.models import UserRequest
from adevx.runtime.app import AdevXRuntime


class CliApp:
    def __init__(self, runtime: AdevXRuntime) -> None:
        self.runtime = runtime

    async def run(self) -> int:
        await self.runtime.start()
        try:
            print("AdevX modular runtime ready. Type /exit to quit.")
            while True:
                user_text = await asyncio.to_thread(input, "\nYou: ")
                user_text = user_text.strip()
                if not user_text:
                    continue
                if user_text.lower() in {"/exit", "exit", "quit"}:
                    break
                request = UserRequest(text=user_text, mode=self.runtime.config.default_mode, session_id="cli")
                response = await self.runtime.handle(request)
                print(f"\nAssistant:\n{response.text}")
        finally:
            await self.runtime.stop()
        return 0

