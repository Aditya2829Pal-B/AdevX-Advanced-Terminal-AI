"""Benchmark helpers for retrieval and local platform diagnostics."""

from __future__ import annotations

import time
from statistics import mean
from typing import Any

from adevx.rag.index import WorkspaceIndexAdapter


class BenchmarkRunner:
    def __init__(self, index: WorkspaceIndexAdapter) -> None:
        self.index = index

    async def run_retrieval(self, queries: list[str] | None = None) -> dict[str, Any]:
        snapshot = await self.index.repo_snapshot()
        symbol_index = snapshot.get("symbol_index", {}) if isinstance(snapshot, dict) else {}
        inferred_queries: list[str] = []
        if isinstance(symbol_index, dict):
            seen: set[str] = set()
            for key, records in symbol_index.items():
                if "." in key or key in seen:
                    continue
                if not isinstance(records, list) or not records:
                    continue
                inferred_queries.append(str(records[0].get("name", key)))
                seen.add(key)
                if len(inferred_queries) >= 6:
                    break
        benchmark_queries = queries or inferred_queries or ["AdevX", "provider router", "memory", "retrieval"]

        timings_ms: list[float] = []
        hit_count = 0
        samples: list[dict[str, Any]] = []
        for query in benchmark_queries[:8]:
            started = time.perf_counter()
            context = await self.index.retrieve_context(query, top_k=3, max_chars=1800)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            timings_ms.append(elapsed_ms)
            if context.strip():
                hit_count += 1
            samples.append(
                {
                    "query": query,
                    "latency_ms": round(elapsed_ms, 2),
                    "hit": bool(context.strip()),
                }
            )

        return {
            "queries": benchmark_queries[:8],
            "samples": samples,
            "hit_rate": round(hit_count / max(1, len(samples)), 3),
            "avg_latency_ms": round(mean(timings_ms), 2) if timings_ms else 0.0,
            "max_latency_ms": round(max(timings_ms), 2) if timings_ms else 0.0,
        }

    @staticmethod
    def format_report(result: dict[str, Any]) -> str:
        lines = ["Retrieval benchmark:"]
        lines.append(f"- queries: {len(result.get('samples', []))}")
        lines.append(f"- hit rate: {result.get('hit_rate', 0.0):.3f}")
        lines.append(f"- avg latency: {result.get('avg_latency_ms', 0.0):.2f} ms")
        lines.append(f"- max latency: {result.get('max_latency_ms', 0.0):.2f} ms")
        for sample in result.get("samples", [])[:8]:
            lines.append(
                f"- {sample.get('query', '')}: "
                f"{'hit' if sample.get('hit') else 'miss'} "
                f"({sample.get('latency_ms', 0.0):.2f} ms)"
            )
        return "\n".join(lines)
