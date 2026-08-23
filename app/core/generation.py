"""Call the LLM with retrieved context (either arm), grounded + cited.

Every generated claim should be traceable back to a specific chunk (vector
arm) or node/edge (graph arm) — that's what evaluation.py's faithfulness
score checks.
"""

from __future__ import annotations


def generate_answer(query: str, retrieval_result, model: str = "meta-llama/Meta-Llama-3.1-70B-Instruct") -> str:
    """Generate a cited answer from one arm's retrieval result.

    TODO:
      - build a prompt that requires inline citations (e.g. [PR #4213] or
        [node: contributor:alice]) for every factual claim
      - call the Nebius-hosted model via the openai-compatible client
      - return the answer text with citations intact, for
        evaluation.py's faithfulness check
    """
    raise NotImplementedError
