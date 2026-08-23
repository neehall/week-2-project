"""Chunk cleaned corpus text, sized to match the embedding model's capacity.

See docs/PLAN.md, "Matching chunk size to embedding capacity":
a 512-token chunk on a 384-dim embedding wastes the chunk's content; a
2000-token chunk on a small model loses signal. Default here targets
text-embedding-3-small (1536 dims) -> 400-600 token chunks.

Code blocks are chunked separately from prose — exact identifiers inside
code (function names, error strings) are what dense retrieval is weakest
at, which is the reason the vector arm is hybrid (see retrieval_vector.py).
"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHUNK_TOKENS = 500  # matches a 1536-dim embedding model; see docs/PLAN.md
DEFAULT_CHUNK_OVERLAP = 50


@dataclass
class Chunk:
    text: str
    is_code: bool
    source_kind: str      # "pr" | "issue" | "rfc" | "module_doc"
    source_number: int
    chunk_index: int


def split_prose_and_code(body: str) -> list[tuple[str, bool]]:
    """Split a cleaned record body into (segment, is_code) pairs.

    TODO: split on fenced code blocks (```), keep each code block as its
    own segment rather than merging with surrounding prose.
    """
    raise NotImplementedError


def chunk_record(record, chunk_tokens: int = DEFAULT_CHUNK_TOKENS) -> list[Chunk]:
    """Chunk one cleaned RawRecord (see ingestion.py) into Chunk objects.

    TODO: use a token-aware splitter (langchain_text_splitters) per
    segment from split_prose_and_code(), sized by chunk_tokens.
    """
    raise NotImplementedError
