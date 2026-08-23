"""Vector-RAG arm: hybrid retrieve -> cross-encoder rerank -> top-5 chunks.

See docs/PLAN.md architecture diagram — this is the left-hand arm that runs
in parallel with retrieval_graph.py on every query.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sentence_transformers import CrossEncoder

from app.common import config

# Small, fast cross-encoder — reranks the fused top ~20 candidates down to
# top_k. Loaded lazily (module-level cache) since it's only needed once
# retrieve() actually runs, and tests/imports shouldn't pay for the download.
_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker: CrossEncoder | None = None


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(_RERANKER_MODEL)
    return _reranker


@dataclass
class RetrievalResult:
    chunks: list
    top_score: float          # used by confidence_gate.py
    arm: str = "vector"


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def retrieve(query: str, store, top_k: int = config.VECTOR_TOP_K) -> RetrievalResult:
    """Hybrid retrieve, then rerank down to top_k chunks."""
    candidates = store.query(query, top_k_per_arm=config.RERANK_CANDIDATE_POOL)
    if not candidates:
        return RetrievalResult(chunks=[], top_score=0.0)

    reranker = _get_reranker()
    pairs = [(query, c.text) for c in candidates]
    # ms-marco cross-encoders return raw logits, not a 0-1 score — sigmoid
    # them so top_score is comparable to confidence_gate.py's 0-1 threshold.
    scores = [_sigmoid(s) for s in reranker.predict(pairs)]

    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
    top = ranked[:top_k]

    return RetrievalResult(
        chunks=[chunk for chunk, _ in top],
        top_score=top[0][1] if top else 0.0,
    )
