"""Plugin registry and lifecycle manager."""

from __future__ import annotations

from adevx.core.contracts import Plugin
from adevx.core.errors import ConfigurationError
from adevx.plugins.base import PluginManifest


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._manifests: dict[str, PluginManifest] = {}

    def register(self, plugin: Plugin, manifest: PluginManifest) -> None:
        if manifest.plugin_id in self._plugins:
            raise ConfigurationError(f"Plugin already registered: {manifest.plugin_id}")
        self._plugins[manifest.plugin_id] = plugin
        self._manifests[manifest.plugin_id] = manifest

    async def start_all(self) -> None:
        for plugin in self._plugins.values():
            await plugin.start()

    async def stop_all(self) -> None:
        for plugin in self._plugins.values():
            await plugin.stop()

    def list_plugins(self) -> list[PluginManifest]:
        return [self._manifests[key] for key in sorted(self._manifests.keys())]

