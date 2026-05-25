"""In-code dependency graph metadata for architecture validation."""

from __future__ import annotations


DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "ui": ["runtime", "core"],
    "runtime": ["agents", "execution", "planning", "providers", "tools", "memory", "rag", "telemetry", "safety", "plugins", "core"],
    "agents": ["execution", "core", "runtime"],
    "execution": ["providers", "tools", "planning", "core", "memory", "rag", "safety"],
    "planning": ["core"],
    "providers": ["core", "execution"],
    "tools": ["core", "safety"],
    "memory": ["core"],
    "rag": ["core"],
    "plugins": ["core"],
    "telemetry": ["core"],
    "safety": ["core"],
}


def validate_no_self_cycles() -> bool:
    for module, deps in DEPENDENCY_GRAPH.items():
        if module in deps:
            return False
    return True

