"""Tool selection intelligence using intent + context scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ToolSelectionEngine:
    def choose(self, text: str, available_tools: list[str], hints: list[str] | None = None) -> str | None:
        lower = text.lower()
        hints = hints or []

        if hints:
            for hint in hints:
                if hint in available_tools:
                    return hint

        patterns = [
            ("analyze_image", r"\b(image|png|jpg|jpeg|gif|webp|bmp|screenshot)\b"),
            ("read_file", r"\b(read|open|show)\b"),
            ("write_file", r"\b(write|create|make file)\b"),
            ("append_file", r"\b(append|add to file)\b"),
            ("search_text", r"\b(search|find|lookup)\b"),
            ("calculate", r"\b(calc|calculate|math|equation)\b"),
            ("fetch_url", r"\b(http://|https://|fetch|get url)\b"),
            ("run_shell", r"\b(shell|command|powershell|terminal)\b"),
            ("summarize_text", r"\b(summarize|summary)\b"),
            ("list_files", r"\b(list files|show files|directory)\b"),
        ]
        for tool_name, pattern in patterns:
            if tool_name in available_tools and re.search(pattern, lower):
                return tool_name

        return available_tools[0] if available_tools else None

