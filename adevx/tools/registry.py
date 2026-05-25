"""Runtime tool registry."""

from __future__ import annotations

from adevx.core.models import ToolInvocation, ToolResult
from adevx.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    async def run(self, invocation: ToolInvocation) -> ToolResult:
        tool = self.get(invocation.name)
        if tool is None:
            return ToolResult(
                call_id=invocation.call_id,
                name=invocation.name,
                output=f"Tool '{invocation.name}' is not registered.",
                success=False,
            )
        return await tool.run(invocation)

