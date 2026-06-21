# AdevX Production Audit

Date: June 21, 2026

## Executive Summary

AdevX is a functional local-first terminal AI platform with a serious architecture foundation: provider routing, offline execution, Ollama support, memory, hybrid RAG, repository intelligence, git intelligence, agent commands, CI, and documentation.

This audit focused on production readiness, not feature expansion. Verified issues were fixed only where they improved reliability, security, correctness, observability, or maintainability without breaking existing commands or storage formats.

## Current Risk Ranking

### Critical

No critical defects were verified during this pass.

### High

1. Secret leakage in provider errors.

Status: fixed.

Risk: malformed API keys and provider errors could surface bearer tokens in terminal output or logs.

Fix: added shared secret redaction via `adevx.core.redaction.redact_secrets()` and applied it to provider/router/CLI error paths.

2. URL fetch could access private/local network targets.

Status: fixed.

Risk: URL fetch tool could be used for local/private network probing.

Fix: added URL parsing, credential rejection, hostname validation, and private/loopback/link-local blocking by default. Local/private fetch can be explicitly enabled with `ADEVX_ALLOW_PRIVATE_URL_FETCH=1`.

3. Shell execution dangerous pattern coverage was too narrow.

Status: fixed.

Risk: shell tool required approval, but blocked only a small set of destructive patterns.

Fix: expanded shell guard and monolith shell blocking for common destructive Windows/Unix patterns.

4. Provider retries could waste time on permanent failures.

Status: fixed.

Risk: auth, quota, invalid model, and bad request failures could be retried unnecessarily.

Fix: added retry filtering so permanent provider errors fail fast while transient errors still retry/fail over.

### Medium

1. Memory writes were not atomic.

Status: fixed.

Risk: interruption during JSON writes could corrupt local memory/progress files.

Fix: added atomic temp-file replacement for legacy and modular memory writes.

2. Agent execution could feel stuck on slow local/provider paths.

Status: fixed.

Risk: `/agent execute` could run too long without a clear stop condition at the CLI command boundary.

Fix: added command-level timeout via `ADEVX_AGENT_TIMEOUT`, defaulting to 120 seconds.

3. Retrieval repeated-query latency was avoidable.

Status: fixed.

Risk: repeated repo/RAG commands performed full ranking work every time.

Fix: added bounded query result cache keyed by query, options, retrieval mode, and index timestamp.

4. Package imports had circular import risk.

Status: previously fixed.

Risk: importing leaf modules could initialize broad runtime paths.

Fix: lazy package exports for major packages.

### Low

1. Dual runtime surface remains.

Status: accepted for compatibility.

Risk: `taskbot.py` and modular `adevx/` still share responsibilities.

Recommendation: continue migrating command behavior into reusable services gradually.

2. Retrieval reranking is heuristic.

Status: accepted.

Risk: not equivalent to neural cross-encoder reranking.

Recommendation: keep heuristic local-first path and optionally add pluggable local reranker later.

3. Metrics are session-local.

Status: accepted.

Risk: no persistent metrics history yet.

Recommendation: add lightweight JSON metrics snapshots before enterprise deployment.

## Architecture Review

Strengths:

- clear modular package boundaries in `adevx/`
- stable CLI preserved in `taskbot.py`
- provider abstraction supports OpenAI-compatible APIs and Ollama
- RAG and repository intelligence are local-first
- agent planning/execution/review pipeline exists
- CI and regression tests are present

Weaknesses:

- production CLI and modular runtime are still partially duplicated
- memory and retrieval have legacy and modular variants
- agent commands are useful but not yet deeply observable step by step
- no persistent production telemetry backend

## Security Review

Improved:

- provider error secret redaction
- private URL blocking
- shell destructive pattern blocking
- path confinement preserved
- command approval preserved

Remaining:

- shell execution still depends on user approval and local trust
- memory is local plaintext JSON
- no team/user permission model
- no audit log tamper resistance

## Reliability Review

Improved:

- permanent provider errors fail fast
- transient provider errors can still retry/fail over
- circuit-open errors are not treated as fresh provider execution failures
- atomic memory/progress writes reduce local corruption risk
- agent execution timeout prevents unbounded command waits

Remaining:

- provider quality still depends on configured external/local models
- long-running autonomous jobs are not yet durable across process restarts
- no production incident telemetry pipeline

## Scalability Review

Current scale target:

- local single-user terminal workflow
- medium-size repositories
- local JSON state

Not yet designed for:

- multi-user hosted SaaS
- team RBAC
- distributed agent execution
- large enterprise monorepos without more indexing optimization

## Performance Review

Measured locally:

- `taskbot` import time: 570.17 ms
- full repo rebuild: 9590.68 ms
- indexed files: 96
- chunks: 1232
- definitions: 624
- cold retrieval: 640.60 ms
- cached retrieval: 0.55 ms

Result:

- repeated retrieval latency improved materially with query caching
- full indexing remains the largest local CPU cost

## Test Review

Current test result:

- 20 tests passing after this hardening pass

Coverage added:

- provider permanent-error retry behavior
- provider fallback
- secret redaction
- private URL blocking
- shell dangerous command blocking

Remaining test gaps:

- deeper end-to-end interactive CLI coverage
- provider integration tests with mocked HTTP servers
- long-running agent cancellation/resume tests
- RAG quality evaluation dataset

## Risk Assessment

Production readiness is now stronger for a local CLI product. For a hosted commercial product, the largest remaining risks are not feature gaps; they are deployment, auth, telemetry, auditability, and long-running job durability.
