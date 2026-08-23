"""Chunk cleaned corpus text, sized to match the embedding model's capacity.

See docs/PLAN.md, "Matching chunk size to embedding capacity":
a 512-token chunk on a 384-dim embedding wastes the chunk's content; a
2000-token chunk on a small model loses signal. Default here reads from
app.common.config (currently all-MiniLM-L6-v2, 384 dims -> 200-300 token
chunks) so chunk size and embedding model stay in sync in one place.

Code blocks are chunked separately from prose — exact identifiers inside
code (function names, error strings) are what dense retrieval is weakest
at, which is the reason the vector arm is hybrid (see retrieval_vector.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.common import config

DEFAULT_CHUNK_TOKENS = config.CHUNK_SIZE_TOKENS
DEFAULT_CHUNK_OVERLAP = config.CHUNK_OVERLAP_TOKENS


@dataclass
class Chunk:
    chunk_id: str          # f"{source_kind}-{source_number}-{chunk_index}"
    text: str
    is_code: bool
    source_kind: str      # "pr" | "issue" | "rfc" | "module_doc"
    source_number: int
    chunk_index: int


def split_prose_and_code(body: str) -> list[tuple[str, bool]]:
    """Split a cleaned record body into (segment, is_code) pairs.

    Splits on fenced code blocks (```), same convention as ingestion.clean()
    uses to avoid touching code while cleaning bot noise: even-indexed
    segments (after ``` split) are prose, odd-indexed are code. Empty/
    whitespace-only segments are dropped.
    """
    segments = body.split("```")
    result: list[tuple[str, bool]] = []
    for i, segment in enumerate(segments):
        text = segment.strip()
        if not text:
            continue
        is_code = i % 2 == 1
        # A fenced block often opens with a language tag on its own line
        # (e.g. "python\ndef foo():"). Strip a lone first line with no
        # spaces — it's a language tag, not code/prose content.
        if is_code:
            first_line, _, rest = text.partition("\n")
            if rest and " " not in first_line and len(first_line) < 20:
                text = rest.strip()
        result.append((text, is_code))
    return result


def _splitter(chunk_tokens: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=chunk_tokens,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    )


def chunk_record(
    record,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    source_kind: str | None = None,
) -> list[Chunk]:
    """Chunk one cleaned RawRecord (see ingestion.py) into Chunk objects.

    Title is prepended to the record's first prose segment so every chunk
    of a PR/issue still carries its title for context, even split ones.
    """
    kind = source_kind or record.kind
    splitter = _splitter(chunk_tokens)

    segments = split_prose_and_code(record.body)
    if not segments or segments[0][1]:  # no prose lead-in, or starts with code
        segments = [(record.title, False)] + segments
    else:
        segments[0] = (f"{record.title}\n\n{segments[0][0]}", False)

    chunks: list[Chunk] = []
    for text, is_code in segments:
        pieces = splitter.split_text(text)
        for piece in pieces:
            chunks.append(
                Chunk(
                    chunk_id=f"{kind}-{record.number}-{len(chunks)}",
                    text=piece,
                    is_code=is_code,
                    source_kind=kind,
                    source_number=record.number,
                    chunk_index=len(chunks),
                )
            )
    return chunks


def chunk_records(records, chunk_tokens: int = DEFAULT_CHUNK_TOKENS) -> list[Chunk]:
    """Chunk a list of cleaned RawRecords into a flat list of Chunks."""
    all_chunks: list[Chunk] = []
    for record in records:
        all_chunks.extend(chunk_record(record, chunk_tokens))
    return all_chunks
