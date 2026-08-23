"""Score both arms on faithfulness, relevance, correct refusal rate, latency.

See docs/PLAN.md, "Evaluation methodology" and "The 10-query comparison
set" (data/eval/test_queries.json). The write-up of where/why each arm
wins is the actual deliverable — these functions just produce the numbers
that write-up is based on.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass


@dataclass
class QueryScore:
    query_id: int
    arm: str  # "vector" | "graph"
    faithfulness: float
    relevance: float
    correctly_refused: bool | None  # None if not a refusal-test query
    latency_seconds: float


def load_test_queries(path: str = "data/eval/test_queries.json") -> list[dict]:
    with open(path) as f:
        return json.load(f)


def score_faithfulness(answer: str, retrieved_context: str) -> float:
    """Does every claim in `answer` trace to `retrieved_context`?

    TODO: LLM-judge rubric (0-1), plus manual spot-check on a sample before
    trusting it for the final report.
    """
    raise NotImplementedError


def score_relevance(retrieved_context: str, query: str) -> float:
    """Does the retrieved context actually address the question."""
    raise NotImplementedError


def run_comparison(queries: list[dict], vector_pipeline, graph_pipeline) -> list[QueryScore]:
    """Run every query through both arms, score, and time each.

    TODO: for each query, run vector_pipeline and graph_pipeline, time
    each with time.perf_counter(), score faithfulness/relevance, and for
    is_refusal_test queries check whether the arm actually refused.
    """
    raise NotImplementedError
