"""Provider adapters and routing."""

from __future__ import annotations

__all__ = ["ProviderRouter"]


def __getattr__(name: str):
    if name == "ProviderRouter":
        from .router import ProviderRouter

        return ProviderRouter
    raise AttributeError(name)
