# AdevX Migration Notes

Date: June 8, 2026

## Breaking Changes

None intended.

This phase was designed to preserve:

- existing CLI behavior
- existing commands
- existing providers
- existing configuration
- existing memory files
- existing RAG functionality
- existing tests

## New Commands Added

- `/memory stats`
- `/memory search <query>`
- `/memory consolidate`
- `/repo symbols`
- `/repo graph`
- `/repo explain <symbol>`
- `/repo references <symbol>`
- `/agent plan <goal>`
- `/agent execute <goal>`
- `/agent review <text>`
- `/git analyze`
- `/git summarize [rev]`
- `/git impact [path|rev-range]`
- `/benchmark`
- `/metrics`

## Storage Compatibility

### Legacy taskbot memory

File:

- `.adevx_memory.json`

Compatibility:

- old `notes` still load and still work
- new optional fields may now appear:
  - `records`
  - `project_memory`
  - `summaries`

### Modular memory

File:

- `.adevx_memory_modular.json`

Compatibility:

- old session arrays still load
- new metadata is additive
- `__meta` may now appear for summaries and project memory

### RAG / repo intelligence

File:

- `.adevx_semantic_index.json`

Compatibility:

- rebuilds remain safe
- new repo metadata is additive
- older index files will be refreshed into the richer structure automatically

## Operational Notes

1. Repository intelligence commands may take longer the first time if the index needs rebuilding.
2. `/agent execute` depends on reachable providers or local models for best results.
3. `/benchmark` always works for retrieval; provider capability scoring depends on configured providers.

## Safe Adoption Path

1. Keep using `taskbot.py` or `adevx.cmd` exactly as before
2. Start using `/repo`, `/memory`, `/agent`, `/git`, `/benchmark`, and `/metrics`
3. Rebuild retrieval index with `/rag rebuild` when repository content changes significantly
