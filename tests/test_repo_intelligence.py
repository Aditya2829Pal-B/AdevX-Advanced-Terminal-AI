from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from adevx.rag.index import WorkspaceIndexAdapter


class RepoIntelligenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = (Path.cwd() / ".adevx_test_tmp" / uuid.uuid4().hex).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "module_a.py").write_text(
            "def helper(value):\n"
            "    return value + 1\n"
            "\n"
            "class Greeter:\n"
            "    def greet(self, name):\n"
            "        return helper(len(name))\n",
            encoding="utf-8",
        )
        (self.root / "module_b.py").write_text(
            "from module_a import helper\n"
            "\n"
            "def consume(data):\n"
            "    return helper(data)\n",
            encoding="utf-8",
        )
        self.index = WorkspaceIndexAdapter(
            workspace_root=self.root,
            path=self.root / ".adevx_test_repo_index.json",
        )
        await self.index.rebuild(chunk_lines=40, overlap_lines=10)

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    async def test_repo_symbols_and_explain(self) -> None:
        symbols = await self.index.repo_symbols_text()
        self.assertIn("helper", symbols)
        self.assertIn("Greeter.greet", symbols)

        explain = await self.index.repo_explain_text("helper")
        self.assertIn("Repository explanation", explain)
        self.assertIn("module_a.py", explain)

    async def test_repo_graph_and_references(self) -> None:
        graph = await self.index.repo_graph_text()
        self.assertIn("Import edges", graph)
        self.assertIn("module_b.py", graph)

        refs = await self.index.repo_references_text("helper")
        self.assertIn("module_a.py", refs)
        self.assertIn("module_b.py", refs)


if __name__ == "__main__":
    unittest.main()
