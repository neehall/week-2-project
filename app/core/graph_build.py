"""Extract entities/relationships from the cleaned corpus and build the graph.

See docs/SCOPE.md, "Graph schema (20+ nodes required)":
- Node types: contributors, PRs, issues/RFCs, modules/packages
- Edge types: authored, reviewed, merged, discusses, depends-on, decided-in

Uses the same cleaned records as the vector arm (see ingestion.py) but
builds a separate index — the two arms don't share state at query time, so
the 10-query comparison (docs/PLAN.md) is measuring a real difference.

Graph store: Neo4j by default. Swap for NetworkX (in-memory, no server) by
changing GraphStore's backend — the node/edge schema stays the same either
way.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Node:
    id: str
    type: str  # "contributor" | "pr" | "issue" | "rfc" | "module"
    properties: dict


@dataclass
class Edge:
    source_id: str
    target_id: str
    type: str  # "authored" | "reviewed" | "merged" | "discusses" | "depends_on" | "decided_in"
    properties: dict


class GraphStore:
    def __init__(self, backend: str = "neo4j"):
        self.backend = backend
        # TODO: connect via neo4j.GraphDatabase.driver(...) using
        # NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD from .env, or init an
        # in-memory networkx.MultiDiGraph() if backend == "networkx".

    def add_node(self, node: Node) -> None:
        raise NotImplementedError

    def add_edge(self, edge: Edge) -> None:
        raise NotImplementedError

    def node_count(self) -> int:
        """Used to confirm the 20+ node requirement is met before submitting."""
        raise NotImplementedError


def extract_entities_and_relations(records: list) -> tuple[list[Node], list[Edge]]:
    """Turn cleaned records (ingestion.py) into nodes and edges.

    TODO:
      - one Node per unique contributor (author + every reviewer)
      - one Node per PR/issue/RFC, one Node per module touched
      - Edge(contributor -authored-> pr), Edge(contributor -reviewed-> pr),
        Edge(pr -merged-> module), Edge(pr -discusses-> issue),
        Edge(rfc -decided_in-> module)
    """
    raise NotImplementedError
