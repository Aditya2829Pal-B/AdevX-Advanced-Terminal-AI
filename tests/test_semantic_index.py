from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path

from adevx.rag.index import WorkspaceIndexAdapter


class SemanticIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = (Path.cwd() / ".adevx_test_tmp" / uuid.uuid4().hex).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "module_a.py").write_text(
            "def foo_bar():\n"
            "    return 1\n"
            "\n"
            "class SampleClass:\n"
            "    def run(self):\n"
            "        return foo_bar()\n",
            encoding="utf-8",
        )
        (self.root / "notes.md").write_text(
            "# Notes\n"
            "AdevX includes incremental semantic indexing and hybrid retrieval.\n",
            encoding="utf-8",
        )
        self._prev_refresh = os.environ.get("ADEVX_RAG_REFRESH_S")
        os.environ["ADEVX_RAG_REFRESH_S"] = "0"
        self.index = WorkspaceIndexAdapter(
            workspace_root=self.root,
            path=self.root / ".adevx_test_semantic_index.json",
        )

    async def asyncTearDown(self) -> None:
        if self._prev_refresh is None:
            os.environ.pop("ADEVX_RAG_REFRESH_S", None)
        else:
            os.environ["ADEVX_RAG_REFRESH_S"] = self._prev_refresh
        shutil.rmtree(self.root, ignore_errors=True)

    async def test_rebuild_and_hybrid_retrieve(self) -> None:
        out = await self.index.rebuild(chunk_lines=40, overlap_lines=10)
        self.assertIn("rebuilt", out.lower())
        status = await self.index.status_text()
        self.assertIn("Files indexed:", status)
        context = await self.index.retrieve_context("foo_bar", top_k=3, max_chars=3000)
        self.assertIn("hybrid retrieval", context.lower())
        self.assertIn("foo_bar", context)

    async def test_incremental_update_detects_new_symbols(self) -> None:
        await self.index.rebuild(chunk_lines=40, overlap_lines=10)
        path = self.root / "module_a.py"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n\ndef new_feature_entrypoint():\n"
            + "    return 'ok'\n",
            encoding="utf-8",
        )
        # Trigger retrieval which triggers incremental refresh.
        context = await self.index.retrieve_context(
            "new_feature_entrypoint",
            top_k=3,
            max_chars=3000,
        )
        self.assertIn("new_feature_entrypoint", context)


if __name__ == "__main__":
    unittest.main()
