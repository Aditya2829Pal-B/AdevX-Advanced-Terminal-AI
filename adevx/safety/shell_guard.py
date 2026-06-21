"""Shell guard for command validation and approval checkpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ShellGuard:
    require_approval: bool = True
    blocked_tokens: tuple[str, ...] = (
        "rm -rf",
        "git reset --hard",
        "format c:",
        "del /f /s",
        "remove-item -recurse",
        "rd /s",
        "rmdir /s",
        ":(){:|:&};:",
    )

    def check(self, command: str) -> tuple[bool, str]:
        raw = command.strip().lower()
        if not raw:
            return False, "Command is empty."
        for token in self.blocked_tokens:
            if token in raw:
                return False, f"Blocked dangerous command pattern: {token}"
        return True, "ok"
