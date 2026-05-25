"""Tool base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod

from adevx.core.models import ToolInvocation, ToolResult


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, invocation: ToolInvocation) -> ToolResult:
        raise NotImplementedError

