from __future__ import annotations

import shutil
import subprocess
import unittest
import uuid
from pathlib import Path

from adevx.core.git_intelligence import GitIntelligence
from adevx.rag.index import WorkspaceIndexAdapter


class GitIntelligenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = (Path.cwd() / ".adevx_test_tmp" / uuid.uuid4().hex).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "AdevX Test"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "adevx@example.com"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.root, check=True, capture_output=True)

        (self.root / "module_a.py").write_text(
            "def helper(value):\n"
            "    return value + 1\n",
            encoding="utf-8",
        )
        (self.root / "module_b.py").write_text(
            "from module_a import helper\n"
            "\n"
            "def consume(data):\n"
            "    return helper(data)\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial repo"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

        (self.root / "module_a.py").write_text(
            "def helper(value):\n"
            "    return value + 2\n",
            encoding="utf-8",
        )
        self.index = WorkspaceIndexAdapter(
            workspace_root=self.root,
            path=self.root / ".adevx_git_index.json",
        )
        await self.index.rebuild(chunk_lines=40, overlap_lines=10)
        self.snapshot = await self.index.repo_snapshot()
        self.git = GitIntelligence(self.root)

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    async def test_summarize_and_impact(self) -> None:
        summary = self.git.summarize("HEAD")
        self.assertIn("initial repo", summary)

        impact = self.git.impact(repo_snapshot=self.snapshot)
        self.assertIn("module_a.py", impact)
        self.assertIn("module_b.py", impact)


if __name__ == "__main__":
    unittest.main()
