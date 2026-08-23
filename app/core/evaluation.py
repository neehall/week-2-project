"""Score both arms on faithfulness, relevance, correct refusal rate, latency.

See docs/PLAN.md, "Evaluation methodology" and "The 10-query comparison
set" (data/eval/test_queries.json). The write-up of where/why each arm
wins is the actual deliverable — these functions just produce the numbers
that write-up is based on.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from app.common import config
from app.core import confidence_gate, generation, retrieval_graph, retrieval_vector


@dataclass
class QueryScore:
    query_id: int
    arm: str  # "vector" | "graph"
    faithfulness: float
    relevance: float
    correctly_refused: bool | None  # None if not a refusal-test query
    latency_seconds: float
    answer: str = ""
    refused: bool = False


def load_test_queries(path: str = str(config.TEST_QUERIES_PATH)) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _judge(prompt: str, model: str = config.GENERATION_MODEL) -> float:
    """Ask Claude to grade something on a 0.0-1.0 scale and parse the score.

    Not a rigorous rubric-driven judge — one call, one number — but good
    enough to rank the two arms against each other, which is what the
    comparison needs. Manual spot-check the actual answers before trusting
    this for the final write-up (see docs/PLAN.md's evaluation section).
    """
    client = generation.get_client()
    response = client.messages.create(
        model=model,
        max_tokens=200,
        system=(
            "You are a strict grader. Respond with exactly one line: "
            "SCORE: <a number between 0.0 and 1.0>. You may add one short "
            "sentence of justification after that line."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    match = re.search(r"SCORE:\s*([0-9]*\.?[0-9]+)", text)
    if not match:
        return 0.0
    return max(0.0, min(1.0, float(match.group(1))))


def score_faithfulness(answer: str, retrieved_context: str) -> float:
    """Does every claim in `answer` trace to `retrieved_context`?"""
    if not answer or not retrieved_context:
        return 0.0
    prompt = (
        f"Retrieved context:\n{retrieved_context}\n\n"
        f"Answer:\n{answer}\n\n"
        "Does every factual claim in the answer trace back to the retrieved "
        "context above? Score 1.0 if every claim is supported by the "
        "context (or the answer correctly says the context doesn't cover "
        "something rather than guessing), 0.0 if it states facts not "
        "present in the context. Partial credit for partially-supported "
        "answers."
    )
    return _judge(prompt)


def score_relevance(retrieved_context: str, query: str) -> float:
    """Does the retrieved context actually address the question."""
    if not retrieved_context:
        return 0.0
    prompt = (
        f"Query: {query}\n\n"
        f"Retrieved context:\n{retrieved_context}\n\n"
        "Does this retrieved context actually help answer the query? "
        "Score 1.0 if highly relevant, 0.0 if irrelevant or off-topic."
    )
    return _judge(prompt)


def _run_vector_arm(query_text: str, vector_store) -> tuple[QueryScore, str]:
    t0 = time.perf_counter()
    result = retrieval_vector.retrieve(query_text, vector_store)
    refused = result.top_score < config.VECTOR_CONFIDENCE_THRESHOLD
    answer = confidence_gate.REFUSAL_MESSAGE if refused else generation.generate_answer(
        query_text, result
    )
    latency = time.perf_counter() - t0

    context = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in result.chunks)
    faithfulness = 0.0 if refused else score_faithfulness(answer, context)
    relevance = 0.0 if refused else score_relevance(context, query_text)

    return (
        QueryScore(
            query_id=0,  # filled in by caller
            arm="vector",
            faithfulness=faithfulness,
            relevance=relevance,
            correctly_refused=None,  # filled in by caller
            latency_seconds=latency,
            answer=answer,
            refused=refused,
        ),
        context,
    )


def _run_graph_arm(query_text: str, graph_store) -> tuple[QueryScore, str]:
    t0 = time.perf_counter()
    result = retrieval_graph.retrieve(query_text, graph_store)
    refused = result.matched_nodes == 0
    answer = confidence_gate.REFUSAL_MESSAGE if refused else generation.generate_answer(
        query_text, result
    )
    latency = time.perf_counter() - t0

    context = result.subgraph_text
    faithfulness = 0.0 if refused else score_faithfulness(answer, context)
    relevance = 0.0 if refused else score_relevance(context, query_text)

    return (
        QueryScore(
            query_id=0,
            arm="graph",
            faithfulness=faithfulness,
            relevance=relevance,
            correctly_refused=None,
            latency_seconds=latency,
            answer=answer,
            refused=refused,
        ),
        context,
    )


def run_comparison(queries: list[dict], vector_store, graph_store) -> list[QueryScore]:
    """Run every query through both arms independently, score, and time each.

    Each arm applies its own refusal rule (vector: top_score below
    threshold; graph: no matched nodes) rather than confidence_gate's
    combined OR — the point of this comparison is to see each arm's
    refusal behavior on its own, not the merged app-facing decision
    app/graph_flow.py makes.
    """
    scores: list[QueryScore] = []
    for q in queries:
        query_text = q["query"]
        is_refusal_test = q.get("is_refusal_test", False)

        vector_score, _ = _run_vector_arm(query_text, vector_store)
        vector_score.query_id = q["id"]
        if is_refusal_test:
            vector_score.correctly_refused = vector_score.refused
        scores.append(vector_score)

        graph_score, _ = _run_graph_arm(query_text, graph_store)
        graph_score.query_id = q["id"]
        if is_refusal_test:
            graph_score.correctly_refused = graph_score.refused
        scores.append(graph_score)

    return scores
