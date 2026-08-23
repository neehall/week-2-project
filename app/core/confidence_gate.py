"""Decide refuse vs. generate, per arm — designed before the happy path.

See docs/PLAN.md, "Designing the refusal path first": a RAG app that
hallucinates when retrieval comes up empty is worse than one that says it
doesn't know. This gate is a real branch in the LangGraph state machine
(app/graph_flow.py), not a prompt instruction the model can ignore.
"""

from __future__ import annotations

from app.common import config

# Single source of truth lives in config.py (VECTOR_CONFIDENCE_THRESHOLD) —
# tune it there against eval results; see docs/PLAN.md. Re-exported here
# under the old name so existing imports of confidence_gate.VECTOR_SCORE_
# THRESHOLD keep working.
VECTOR_SCORE_THRESHOLD = config.VECTOR_CONFIDENCE_THRESHOLD
REFUSAL_MESSAGE = config.REFUSAL_MESSAGE


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
