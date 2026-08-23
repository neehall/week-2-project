"""GraphRAG arm: entity match -> 1-2 hop traversal -> serialized subgraph.

See docs/PLAN.md architecture diagram — this is the right-hand arm that
runs in parallel with retrieval_vector.py on every query.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrievalResult:
    subgraph_text: str        # serialized nodes/edges, fed to generation.py
    matched_nodes: int
    arm: str = "graph"


def retrieve(query: str, store, max_hops: int = 2) -> RetrievalResult:
    """Entity-match the query against graph nodes, traverse, serialize.

    TODO:
      1. extract candidate entity names from the query (contributor names,
         PR/issue numbers, module names)
      2. look up matching nodes in `store` (graph_build.GraphStore)
      3. traverse up to max_hops from each matched node
      4. serialize the resulting subgraph to text for generation.py
      5. matched_nodes = 0 signals confidence_gate.py to refuse
    """
    raise NotImplementedError
