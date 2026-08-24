"""Dense embeddings + BM25 sparse index, fused at query time.

See docs/PLAN.md, "Why the vector arm is hybrid, not pure dense":
- Dense retrieval catches paraphrase / semantic intent, misses exact
  identifiers (PR numbers, usernames, error codes).
- BM25 catches those exact identifiers, misses semantic intent.
- Fuse both result sets (reciprocal rank fusion), then rerank the merged
  top ~20 with a cross-encoder down to the top 5 that reach the LLM.

Embedding model defaults to a local sentence-transformers model (see
app.common.config) so this runs with no API key. Swap EMBEDDING_MODEL for
a Nebius-hosted model once NEBIUS_API_KEY is set — only config.py needs to
change, this module reads the model name generically.
"""

from __future__ import annotations

import re

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

from app.common import config

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase word-ish tokenizer for BM25 — good enough for identifiers
    (PR numbers, usernames, function names) without pulling in a full NLP
    tokenizer for a term-frequency index.
    """
    return _TOKEN_RE.findall(text.lower())


class HybridVectorStore:
    """Wraps a Chroma dense index and a BM25 sparse index over the same chunks."""

    def __init__(self, embedding_model: str = config.EMBEDDING_MODEL, persist_dir: str | None = None):
        self.embedding_model = embedding_model
        self._client = (
            chromadb.PersistentClient(path=persist_dir)
            if persist_dir
            else chromadb.Client()
        )
        self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=embedding_model
        )
        # get_or_create so re-running against a persistent dir doesn't
        # error on a collection that already exists.
        self._collection = self._client.get_or_create_collection(
            name="corpus_chunks", embedding_function=self._embedding_fn
        )
        self._bm25: BM25Okapi | None = None
        self._bm25_chunk_ids: list[str] = []
        self.chunks_by_id: dict[str, object] = {}

    def add_chunks(self, chunks: list) -> None:
        """Embed and index chunks in both the dense and sparse stores."""
        if not chunks:
            return

        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [
            {
                "is_code": c.is_code,
                "source_kind": c.source_kind,
                "source_number": c.source_number,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ]
        # Chroma enforces a max batch size per add() call (observed: 5461,
        # tied to the underlying sqlite parameter limit) — silent at small
        # corpus sizes, a hard InternalError once chunk count crosses it
        # (hit at 1000 records / 8105 chunks). Batch defensively rather
        # than assume the corpus stays small.
        batch_size = 2000
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            self._collection.add(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

        for c in chunks:
            self.chunks_by_id[c.chunk_id] = c

        # BM25 has no incremental-add API — rebuild over the full chunk set
        # each time add_chunks is called. Fine for a one-shot ingestion run;
        # would need reworking for streaming updates.
        self._bm25_chunk_ids = list(self.chunks_by_id.keys())
        tokenized_corpus = [
            _tokenize(self.chunks_by_id[cid].text) for cid in self._bm25_chunk_ids
        ]
        self._bm25 = BM25Okapi(tokenized_corpus)

    def query(self, query_text: str, top_k_per_arm: int = 20) -> list:
        """Run dense + BM25 search, fuse via reciprocal rank fusion.

        Returns the fused top_k_per_arm candidates, unranked by the final
        cross-encoder (that happens in retrieval_vector.py's rerank step).
        """
        n_dense = min(top_k_per_arm, self._collection.count())
        dense_ids: list[str] = []
        if n_dense > 0:
            dense_result = self._collection.query(query_texts=[query_text], n_results=n_dense)
            dense_ids = dense_result["ids"][0]

        sparse_ids: list[str] = []
        if self._bm25 is not None and self._bm25_chunk_ids:
            scores = self._bm25.get_scores(_tokenize(query_text))
            ranked = sorted(
                zip(self._bm25_chunk_ids, scores), key=lambda pair: pair[1], reverse=True
            )
            sparse_ids = [cid for cid, score in ranked[:top_k_per_arm] if score > 0]

        fused_ids = reciprocal_rank_fusion(dense_ids, sparse_ids)
        return [self.chunks_by_id[cid] for cid in fused_ids[:top_k_per_arm]]


def reciprocal_rank_fusion(dense_results: list, sparse_results: list, k: int = 60) -> list:
    """Combine two ranked result lists via RRF: score = sum(1 / (k + rank))."""
    scores: dict = {}
    for results in (dense_results, sparse_results):
        for rank, item_id in enumerate(results):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)
