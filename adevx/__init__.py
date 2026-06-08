"""AdevX production architecture package."""

from __future__ import annotations

__all__ = ["AdevXRuntime"]


def __getattr__(name: str):
    if name == "AdevXRuntime":
        from .runtime.app import AdevXRuntime

        return AdevXRuntime
    raise AttributeError(name)
