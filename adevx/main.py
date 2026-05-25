"""Modular runtime entrypoint."""

from __future__ import annotations

import asyncio

from adevx.runtime.app import AdevXRuntime
from adevx.ui.cli import CliApp


async def _run() -> int:
    runtime = AdevXRuntime.create()
    app = CliApp(runtime)
    return await app.run()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())

