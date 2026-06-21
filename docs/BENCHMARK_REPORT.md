# AdevX Benchmark Report

Date: June 21, 2026

## Test Conditions

- Workspace: current AdevX repository
- Environment: local/offline-friendly validation
- Retrieval engine: advanced hybrid retrieval in `WorkspaceIndexAdapter`
- Provider benchmarks: not fully executed in this report because this production pass intentionally avoided cloud/API calls

## Retrieval Benchmark

Measured on the current repository after a fresh rebuild:

- `taskbot` import time: 570.17 ms
- index initialization: 0.71 ms
- full index rebuild: 9590.68 ms
- indexed files: 96
- chunks: 1232
- definitions: 624
- cold retrieval: 640.60 ms
- cached retrieval: 0.55 ms
- cache result parity: true

## Interpretation

What is good:

- symbol-oriented queries resolve correctly
- the new index can answer definition and reference questions with no external provider
- repeated retrieval is now fast enough for interactive command workflows

What still needs work:

- cold retrieval is acceptable for offline repository intelligence, but still high for IDE-grade live search
- graph traversal is currently file-and-symbol aware, but not yet full semantic dependency reasoning
- reranking is heuristic, not model-based

## Provider Benchmark Status

Provider benchmarking is available through:

- `/benchmark`
- `AdevXBot._run_capability_benchmark()`
- `/health`

This report does not include live provider latency or answer-quality scores because the production hardening pass avoided API calls and rate-limit risk.

## Recommendation

Next performance priorities:

1. Cache repo snapshots between repeated `/repo` queries
2. Add incremental symbol-only refresh path for low-latency lookups
3. Add reverse-import cache for faster impact analysis
4. Add optional persistent benchmark history for regression tracking
