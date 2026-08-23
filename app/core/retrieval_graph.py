"""GraphRAG arm: entity match -> 1-2 hop traversal -> serialized subgraph.

See docs/PLAN.md architecture diagram — this is the right-hand arm that
runs in parallel with retrieval_vector.py on every query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.common import config

_PR_ISSUE_REF_RE = re.compile(r"#(\d+)")
_RECORD_KINDS = ("pr", "issue", "rfc")


@dataclass
class RetrievalResult:
    subgraph_text: str        # serialized nodes/edges, fed to generation.py
    matched_nodes: int
    arm: str = "graph"


def _match_entities(query: str, store) -> set[str]:
    """Extract candidate entity names from the query and resolve them
    against nodes already in the graph.
    """
    matched: set[str] = set()
    query_lower = query.lower()

    # PR/issue/RFC numbers, e.g. "#4213"
    for number in _PR_ISSUE_REF_RE.findall(query):
        for kind in _RECORD_KINDS:
            node_id = f"{kind}:{number}"
            if store.get_node(node_id) is not None:
                matched.add(node_id)

    # Contributor usernames — substring match against the query. "unknown"
    # is a cleaning placeholder (see ingestion.clean()), not a real entity.
    for node_id in store.node_ids_by_type("contributor"):
        username = node_id.split(":", 1)[1]
        if username.lower() != "unknown" and username.lower() in query_lower:
            matched.add(node_id)

    # Module names
    for node_id in store.node_ids_by_type("module"):
        module_name = node_id.split(":", 1)[1]
        if module_name.lower() in query_lower:
            matched.add(node_id)

    return matched


def _serialize_subgraph(subgraph) -> str:
    """Flatten a NetworkX subgraph into text for generation.py.

    Each line is one fact — a node's properties or one directed edge —
    kept simple and literal on purpose (see docs/PLAN.md's "Subgraph ->
    text serialization" failure point: the harder problem is deciding
    what to include, not how to format it).
    """
    lines: list[str] = []
    for node_id, attrs in subgraph.nodes(data=True):
        node_type = attrs.get("type", "?")
        props = {k: v for k, v in attrs.items() if k != "type" and v is not None}
        props_str = f" {props}" if props else ""
        lines.append(f"[{node_type}] {node_id}{props_str}")

    lines.append("")  # blank line between node and edge listings
    for source_id, target_id, attrs in subgraph.edges(data=True):
        lines.append(f"{source_id} -{attrs.get('type', '?')}-> {target_id}")

    return "\n".join(lines)


def retrieve(query: str, store, max_hops: int = config.GRAPH_MAX_HOPS) -> RetrievalResult:
    """Entity-match the query against graph nodes, traverse, serialize."""
    matched = _match_entities(query, store)
    if not matched:
        return RetrievalResult(subgraph_text="", matched_nodes=0)

    subgraph = store.ego_subgraph(matched, max_hops)
    return RetrievalResult(
        subgraph_text=_serialize_subgraph(subgraph),
        matched_nodes=len(matched),
    )
