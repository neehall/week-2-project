"""LangGraph state machine wiring both retrieval arms through the gate.

parse_query -> {retrieve_vector, retrieve_graph} -> confidence_gate -> {generate, refuse}

See docs/PLAN.md for the full diagram and reasoning. This is the actual
mechanism the interactive app runs a single query through. The "compare
GraphRAG vs vector RAG" eval harness (app/core/evaluation.py) calls
retrieval_vector/retrieval_graph/generation directly per arm instead of
going through this combined flow — it needs both arms' answers side by
side, not the one merged answer this graph produces.
"""

from __future__ import annotations

import functools
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core import confidence_gate, generation, retrieval_graph, retrieval_vector


class GraphState(TypedDict, total=False):
    query: str
    vector_result: object
    graph_result: object
    answer: str
    refused: bool


def parse_query(state: GraphState) -> dict:
    """Entry node. Just whitespace normalization — both retrieve()
    functions already do their own entity/keyword extraction internally,
    so no separate entity-hinting pass is needed here.

    Returns only the keys it updates rather than the full state — with
    two parallel branches downstream, a node returning the whole state
    dict makes every unrelated key look like a second write to the same
    channel in the same step, which LangGraph rejects as a conflicting
    update.
    """
    return {"query": state["query"].strip()}


def node_retrieve_vector(state: GraphState, vector_store) -> dict:
    # NB: the parameter can't be named "store" — LangGraph reserves that
    # name for its own BaseStore dependency injection and will silently
    # override a functools.partial-bound value with None.
    return {"vector_result": retrieval_vector.retrieve(state["query"], vector_store)}


def node_retrieve_graph(state: GraphState, graph_store) -> dict:
    return {"graph_result": retrieval_graph.retrieve(state["query"], graph_store)}


def node_confidence_gate(state: GraphState) -> dict:
    refused = confidence_gate.should_refuse(state["vector_result"], state["graph_result"])
    return {"refused": refused}


def node_generate_or_refuse(state: GraphState) -> dict:
    if state["refused"]:
        return {"answer": confidence_gate.REFUSAL_MESSAGE}

    vector_result = state["vector_result"]
    graph_result = state["graph_result"]
    vector_confident = vector_result.top_score >= confidence_gate.VECTOR_SCORE_THRESHOLD

    # Prefer the vector arm when it clears its own threshold — it carries a
    # graded confidence score, whereas the graph arm's matched_nodes is a
    # coarser binary signal (see docs/PLAN.md's "weak confidence signal"
    # failure point). Fall back to the graph arm only when vector is weak
    # but graph still found something (should_refuse already guarantees at
    # least one arm is confident by this point).
    chosen = vector_result if vector_confident else graph_result
    return {"answer": generation.generate_answer(state["query"], chosen)}


def build_graph(vector_store, graph_store):
    """Wire the nodes above into a compiled LangGraph StateGraph.

    vector_store/graph_store are bound into their retrieval nodes via
    functools.partial at build time — LangGraph node functions take only
    (state, [config]), so the stores can't be passed at invoke time.
    """
    graph = StateGraph(GraphState)

    graph.add_node("parse_query", parse_query)
    graph.add_node(
        "retrieve_vector", functools.partial(node_retrieve_vector, vector_store=vector_store)
    )
    graph.add_node(
        "retrieve_graph", functools.partial(node_retrieve_graph, graph_store=graph_store)
    )
    graph.add_node("confidence_gate", node_confidence_gate)
    graph.add_node("generate_or_refuse", node_generate_or_refuse)

    graph.add_edge(START, "parse_query")
    # Fan out: both retrieval arms run off parse_query independently.
    graph.add_edge("parse_query", "retrieve_vector")
    graph.add_edge("parse_query", "retrieve_graph")
    # Fan in: confidence_gate waits for both branches before running.
    graph.add_edge("retrieve_vector", "confidence_gate")
    graph.add_edge("retrieve_graph", "confidence_gate")
    graph.add_edge("confidence_gate", "generate_or_refuse")
    graph.add_edge("generate_or_refuse", END)

    return graph.compile()
