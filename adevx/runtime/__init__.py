"""Runtime lifecycle and orchestration entrypoints."""

from __future__ import annotations

__all__ = ["AdevXRuntime"]


def __getattr__(name: str):
    if name == "AdevXRuntime":
        from .app import AdevXRuntime

        return AdevXRuntime
    raise AttributeError(name)
