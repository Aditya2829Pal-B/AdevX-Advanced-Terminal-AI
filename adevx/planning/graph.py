"""Plan graph structures for future DAG scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PlanNode:
    node_id: str
    capability: str
    title: str
    dependencies: list[str] = field(default_factory=list)
    allow_parallel: bool = False


@dataclass(slots=True)
class PlanGraph:
    nodes: dict[str, PlanNode] = field(default_factory=dict)

    def add_node(self, node: PlanNode) -> None:
        self.nodes[node.node_id] = node

    def topological_order(self) -> list[PlanNode]:
        # Deterministic placeholder order; replace with true topological sort.
        return [self.nodes[key] for key in sorted(self.nodes.keys())]

