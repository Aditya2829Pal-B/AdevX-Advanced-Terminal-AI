"""Built-in tool adapters that wrap current taskbot tool implementations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from adevx.core.models import ToolInvocation, ToolResult
from adevx.safety.shell_guard import ShellGuard
from adevx.tools.base import BaseTool

# Reuse existing battle-tested implementations from the monolith during migration.
import taskbot


@dataclass(slots=True)
class FunctionTool(BaseTool):
    name: str
    description: str
    func: Callable[..., str]

    async def run(self, invocation: ToolInvocation) -> ToolResult:
        try:
            output = await asyncio.to_thread(self.func, **invocation.arguments)
            return ToolResult(
                call_id=invocation.call_id,
                name=self.name,
                output=output,
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                call_id=invocation.call_id,
                name=self.name,
                output=str(exc),
                success=False,
            )


class GuardedShellTool(BaseTool):
    name = "run_shell"
    description = "Run shell command with safety guard and explicit approval callback."

    def __init__(self, guard: ShellGuard) -> None:
        self._guard = guard

    async def run(self, invocation: ToolInvocation) -> ToolResult:
        command = str(invocation.arguments.get("command", "")).strip()
        allow, reason = self._guard.check(command)
        if not allow:
            return ToolResult(
                call_id=invocation.call_id,
                name=self.name,
                output=reason,
                success=False,
            )
        timeout_seconds = int(invocation.arguments.get("timeout_seconds", 30))
        output = await asyncio.to_thread(
            taskbot.tool_run_shell,
            command,
            timeout_seconds,
            taskbot.ask_shell_approval,
        )
        return ToolResult(
            call_id=invocation.call_id,
            name=self.name,
            output=output,
            success=True,
        )


def build_default_tools(guard: ShellGuard) -> list[BaseTool]:
    return [
        FunctionTool("list_files", "List files in workspace directory.", taskbot.tool_list_files),
        FunctionTool("read_file", "Read file content.", taskbot.tool_read_file),
        FunctionTool("write_file", "Write file content.", taskbot.tool_write_file),
        FunctionTool("append_file", "Append file content.", taskbot.tool_append_file),
        FunctionTool("search_text", "Search text in files.", taskbot.tool_search_text),
        FunctionTool("calculate", "Evaluate safe arithmetic expression.", taskbot.tool_calculate),
        FunctionTool("fetch_url", "Fetch URL text content.", taskbot.tool_fetch_url),
        FunctionTool("summarize_text", "Summarize text.", taskbot.tool_summarize_text),
        FunctionTool("analyze_image", "Analyze image metadata.", taskbot.tool_analyze_image),
        GuardedShellTool(guard),
    ]

