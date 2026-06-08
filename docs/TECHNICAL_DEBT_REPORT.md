# AdevX Technical Debt Report

Date: June 8, 2026

## Active Debt Areas

### 1. Dual Runtime Surface

- `taskbot.py` remains the public CLI
- `adevx/` remains the long-term architecture path

This is intentional for compatibility, but it means some product logic still exists in both places.

### 2. Dual Memory Systems

- legacy memory: `.adevx_memory.json`
- modular memory: `.adevx_memory_modular.json`

Both now support richer flows, but they are still separate stores.

### 3. Dual Retrieval Systems

- legacy `ProjectRAGStore` still powers stable taskbot RAG commands
- modular `WorkspaceIndexAdapter` now powers advanced repo intelligence

This preserves compatibility, but it also means retrieval logic is not fully unified yet.

### 4. Heuristic Reranker

The new retrieval pipeline includes reranking, but it is currently local and heuristic rather than a true neural cross-encoder. This is a deliberate local-first compromise.

### 5. Agent Execution UX

The autonomous engine is usable now through slash commands, but it is still closer to an engineering runtime than a polished end-user agent product.

### 6. Metrics Persistence

The current `/metrics` view is session-local command telemetry, not a persistent observability backend.

## Priority Debt To Pay Down Next

1. Unify legacy and modular retrieval behind one shared storage contract
2. Unify legacy and modular memory contracts
3. Add richer repo graph traversal and symbol-to-file dependency mapping
4. Add persistent telemetry snapshots
5. Add stronger provider benchmarking and replayable eval fixtures

## Debt That Should Not Be Paid Down Prematurely

1. Full rewrite of `taskbot.py`
2. Forced migration of old memory files
3. Removal of legacy commands before the modular command surface fully replaces them

Those changes would create unnecessary compatibility risk right now.
