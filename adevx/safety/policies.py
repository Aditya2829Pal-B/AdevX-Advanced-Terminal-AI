"""Safety policy engine hooks for prompt/tool/runtime enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SafetyDecision:
    allow: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SafetyPolicyEngine:
    def evaluate_prompt(self, text: str) -> SafetyDecision:
        if not text.strip():
            return SafetyDecision(allow=False, reason="Empty prompt is not allowed.")
        return SafetyDecision(allow=True)

    def evaluate_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> SafetyDecision:
        if tool_name == "run_shell" and not arguments.get("command", "").strip():
            return SafetyDecision(allow=False, reason="Shell command cannot be empty.")
        return SafetyDecision(allow=True)

