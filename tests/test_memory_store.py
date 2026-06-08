from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from adevx.memory.json_store import JsonMemoryStore


class MemoryStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = (Path.cwd() / ".adevx_test_tmp" / uuid.uuid4().hex).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = JsonMemoryStore(self.root / ".adevx_memory_test.json")

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    async def test_stats_and_search(self) -> None:
        await self.store.add("s1", "AdevX uses provider routing", {"kind": "semantic"})
        await self.store.add("s1", "Investigated routing timeout in provider chain", {"kind": "episodic"})
        await self.store.add("s1", "Project memory for repo indexing", {"kind": "project"})

        stats = await self.store.stats("s1")
        self.assertEqual(stats["total_records"], 3)
        self.assertEqual(stats["kind_counts"]["semantic"], 1)

        hits = await self.store.search("provider routing", session_id="s1", limit=3)
        self.assertTrue(hits)
        self.assertIn("provider routing", hits[0].text.lower())

    async def test_consolidate(self) -> None:
        for index in range(6):
            await self.store.add("s2", f"Conversation note {index} about indexing and retrieval", {"kind": "conversation"})
        result = await self.store.consolidate("s2", keep_recent=3)
        self.assertGreaterEqual(result["collapsed"], 3)
        self.assertIn("Session memory consolidation", result["summary"])


if __name__ == "__main__":
    unittest.main()
