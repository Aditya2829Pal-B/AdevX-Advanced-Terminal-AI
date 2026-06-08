"""Execution-layer orchestration primitives."""

from __future__ import annotations

__all__ = ["ExecutionOrchestrator"]


def __getattr__(name: str):
    if name == "ExecutionOrchestrator":
        from .orchestrator import ExecutionOrchestrator

        return ExecutionOrchestrator
    raise AttributeError(name)
