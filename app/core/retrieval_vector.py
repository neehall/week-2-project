"""Vector-RAG arm: hybrid retrieve -> cross-encoder rerank -> top-5 chunks.

See docs/PLAN.md architecture diagram — this is the left-hand arm that runs
in parallel with retrieval_graph.py on every query.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrievalResult:
    chunks: list
    top_score: float          # used by confidence_gate.py
    arm: str = "vector"


def retrieve(query: str, store, top_k: int = 5) -> RetrievalResult:
    """Hybrid retrieve, then rerank down to top_k chunks.

    TODO:
      1. store.query(query) -> fused candidates (see vector_store.py)
      2. rerank candidates with a cross-encoder
         (sentence_transformers.CrossEncoder), keep top_k
      3. return RetrievalResult with top_score = the reranked top chunk's
         score, so confidence_gate.py can threshold on it
    """
    raise NotImplementedError
