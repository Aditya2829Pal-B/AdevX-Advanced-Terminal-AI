from __future__ import annotations

import unittest

from taskbot import AdevXBot, FallbackBot, MemoryStore, ProjectRAGStore, ToolRegistry


class TaskbotCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bot = AdevXBot(
            FallbackBot(ToolRegistry(), MemoryStore(), ProjectRAGStore()),
            None,
            [],
        )

    def test_agent_plan_command(self) -> None:
        result = self.bot.ask("/agent plan implement search")
        self.assertIn("Agent plan:", result)
        self.assertIn("Tasks:", result)

    def test_metrics_command_after_memory(self) -> None:
        self.bot.ask("/memory stats")
        result = self.bot.ask("/metrics")
        self.assertIn("AdevX command metrics:", result)
        self.assertIn("memory", result)


if __name__ == "__main__":
    unittest.main()
