"""Decide refuse vs. generate, per arm — designed before the happy path.

See docs/PLAN.md, "Designing the refusal path first": a RAG app that
hallucinates when retrieval comes up empty is worse than one that says it
doesn't know. This gate is a real branch in the LangGraph state machine
(app/graph_flow.py), not a prompt instruction the model can ignore.
"""

from __future__ import annotations


VECTOR_SCORE_THRESHOLD = 0.65  # tune against eval results; see docs/PLAN.md
REFUSAL_MESSAGE = (
    "I couldn't find this in the LangChain repo data I've indexed. "
    "Try rephrasing, or this may be outside what I've ingested."
)


def should_refuse(vector_result, graph_result) -> bool:
    """True if neither arm produced sufficient evidence.

    - vector arm refuses when top reranked score < VECTOR_SCORE_THRESHOLD
    - graph arm refuses when matched_nodes == 0 (no entity match, or an
      empty traversal)
    - refuse outright only if BOTH arms are below threshold — either arm
      alone having evidence is enough to attempt an answer
    """
    vector_confident = vector_result.top_score >= VECTOR_SCORE_THRESHOLD
    graph_confident = graph_result.matched_nodes > 0
    return not (vector_confident or graph_confident)
