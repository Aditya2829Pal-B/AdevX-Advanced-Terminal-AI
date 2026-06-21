from __future__ import annotations

import os
import unittest

from adevx.core.redaction import redact_secrets
from adevx.safety.shell_guard import ShellGuard
from taskbot import ToolError, _validate_fetch_url, tool_run_shell


class SecurityHardeningTests(unittest.TestCase):
    def test_redacts_known_api_key_patterns(self) -> None:
        message = "failed with Bearer sk-proj-supersecret123456789"
        redacted = redact_secrets(message)
        self.assertNotIn("sk-proj-supersecret", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_url_fetch_blocks_localhost_by_default(self) -> None:
        old = os.environ.pop("ADEVX_ALLOW_PRIVATE_URL_FETCH", None)
        try:
            with self.assertRaises(ToolError):
                _validate_fetch_url("http://localhost:11434/api/tags")
        finally:
            if old is not None:
                os.environ["ADEVX_ALLOW_PRIVATE_URL_FETCH"] = old

    def test_shell_guard_blocks_destructive_patterns(self) -> None:
        guard = ShellGuard()
        allowed, reason = guard.check("Remove-Item -Recurse C:\\tmp\\x")
        self.assertFalse(allowed)
        self.assertIn("Blocked dangerous command pattern", reason)

    def test_taskbot_shell_tool_blocks_without_prompting(self) -> None:
        with self.assertRaises(ToolError):
            tool_run_shell("git reset --hard", approval_callback=lambda _cmd: True)


if __name__ == "__main__":
    unittest.main()
