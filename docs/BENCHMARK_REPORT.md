# AdevX Benchmark Report

Date: June 8, 2026

## Test Conditions

- Workspace: current AdevX repository
- Environment: local/offline-friendly validation
- Retrieval engine: advanced hybrid retrieval in `WorkspaceIndexAdapter`
- Provider benchmarks: not fully executed in this report because online providers were not configured during validation

## Retrieval Benchmark

Measured on the current repository after a fresh rebuild:

- queries: 6
- hit rate: 1.000
- average latency: 848.56 ms
- max latency: 928.49 ms

Sample queries:

- `main`: hit, 799.55 ms
- `calls`: hit, 871.11 ms
- `local`: hit, 855.50 ms
- `work`: hit, 904.24 ms
- `normalize_mode_name`: hit, 928.49 ms
- `mode_instruction_text`: hit, 732.49 ms

## Interpretation

What is good:

- hit rate was perfect on sampled repository-native queries
- symbol-oriented queries resolve correctly
- the new index can answer definition and reference questions with no external provider

What still needs work:

- average latency is acceptable for offline repository intelligence, but still high for interactive IDE-grade usage
- graph traversal is currently file-and-symbol aware, but not yet full semantic dependency reasoning
- reranking is heuristic, not model-based

## Provider Benchmark Status

Provider benchmarking is available through:

- `/benchmark`
- `AdevXBot._run_capability_benchmark()`
- `/health`

This report does not include live provider latency or answer-quality scores because those depend on configured API keys or local Ollama availability at runtime.

## Recommendation

Next performance priorities:

1. Cache repo snapshots between repeated `/repo` queries
2. Add incremental symbol-only refresh path for low-latency lookups
3. Add reverse-import cache for faster impact analysis
4. Add optional persistent benchmark history for regression tracking
