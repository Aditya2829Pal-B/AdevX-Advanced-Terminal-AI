"""Automation phase runner scaffold (phase1/phase2/phase3...)."""

from __future__ import annotations

from dataclasses import dataclass

from adevx.rag.index import WorkspaceIndexAdapter


@dataclass(slots=True)
class PhaseRunner:
    rag_index: WorkspaceIndexAdapter

    async def run_phase2(self) -> dict[str, str]:
        rag_info = await self.rag_index.rebuild(chunk_lines=60, overlap_lines=15)
        return {
            "phase": "phase2",
            "rag": rag_info,
            "status": "ok",
        }

