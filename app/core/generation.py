"""Call the LLM with retrieved context (either arm), grounded + cited.

Every generated claim should be traceable back to a specific chunk (vector
arm) or node/edge (graph arm) — that's what evaluation.py's faithfulness
score checks.

Uses Claude via the official Anthropic SDK (see docs/PLAN.md — originally
scoped for a Nebius-hosted model, swapped since NEBIUS_API_KEY isn't set;
needs ANTHROPIC_API_KEY in .env instead).
"""

from __future__ import annotations

import anthropic

from app.common import config

SYSTEM_PROMPT = (
    "You answer questions about the langchain-ai/langchain GitHub repo using "
    "only the context provided below — either retrieved text chunks or a "
    "serialized graph subgraph. Every factual claim must carry an inline "
    "citation to its source: [chunk_id] for a vector chunk (e.g. "
    "[pr-4213-0]), or a node id for a graph fact (e.g. [contributor:alice]). "
    "If the context doesn't support an answer, say so explicitly rather "
    "than guessing or using outside knowledge."
)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """Shared, lazily-created Anthropic client — also used by
    evaluation.py's LLM-judge calls, so both modules reuse one client
    instance instead of each opening their own.
    """
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # resolves ANTHROPIC_API_KEY from env
    return _client


def _format_context(retrieval_result) -> str:
    """Render either arm's retrieval result as citable text."""
    if retrieval_result.arm == "vector":
        return "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in retrieval_result.chunks)
    return retrieval_result.subgraph_text  # graph arm: already serialized


def generate_answer(
    query: str, retrieval_result, model: str = config.GENERATION_MODEL
) -> str:
    """Generate a cited answer from one arm's retrieval result."""
    context = _format_context(retrieval_result)
    client = get_client()

    response = client.messages.create(
        model=model,
        max_tokens=config.GENERATION_MAX_TOKENS,
        # Claude Opus 5's adaptive thinking shares this token budget with
        # the visible answer. On a large graph subgraph (a big module's
        # worth of PRs/edges) thinking alone consumed the entire budget,
        # leaving stop_reason "max_tokens" and zero visible text — capping
        # effort keeps more of the budget going to the actual answer. See
        # config.GENERATION_MAX_TOKENS's comment for the full story.
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {query}",
            }
        ],
    )

    return "".join(block.text for block in response.content if block.type == "text")
