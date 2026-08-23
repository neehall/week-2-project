"""Dense embeddings + BM25 sparse index, fused at query time.

See docs/PLAN.md, "Why the vector arm is hybrid, not pure dense":
- Dense retrieval catches paraphrase / semantic intent, misses exact
  identifiers (PR numbers, usernames, error codes).
- BM25 catches those exact identifiers, misses semantic intent.
- Fuse both result sets (reciprocal rank fusion), then rerank the merged
  top ~20 with a cross-encoder down to the top 5 that reach the LLM.
"""

from __future__ import annotations


class HybridVectorStore:
    """Wraps a Chroma dense index and a BM25 sparse index over the same chunks."""

    def __init__(self, embedding_model: str = "text-embedding-3-small"):
        self.embedding_model = embedding_model
        # TODO: init chromadb collection + rank_bm25.BM25Okapi over the
        # same chunk set, keeping a shared chunk_id -> Chunk lookup.

    def add_chunks(self, chunks: list) -> None:
        """Embed and index chunks in both the dense and sparse stores."""
        raise NotImplementedError

    def query(self, query_text: str, top_k_per_arm: int = 20) -> list:
        """Run dense + BM25 search, fuse via reciprocal rank fusion.

        Returns the fused top_k_per_arm candidates, unranked by the final
        cross-encoder (that happens in retrieval_vector.py's rerank step).
        """
        raise NotImplementedError


def reciprocal_rank_fusion(dense_results: list, sparse_results: list, k: int = 60) -> list:
    """Combine two ranked result lists via RRF: score = sum(1 / (k + rank))."""
    raise NotImplementedError
