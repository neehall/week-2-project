"""LangGraph state machine wiring both retrieval arms through the gate.

parse_query -> {retrieve_vector, retrieve_graph} -> confidence_gate -> {generate, refuse}

See docs/PLAN.md for the full diagram and reasoning. This is the actual
mechanism the "compare GraphRAG vs vector RAG" deliverable runs on — both
arms execute on every query, so the eval harness (app/core/evaluation.py)
can score them against the same run.
"""

from __future__ import annotations

from typing import TypedDict

from app.core import confidence_gate, generation, retrieval_graph, retrieval_vector


class GraphState(TypedDict, total=False):
    query: str
    vector_result: object
    graph_result: object
    answer: str
    refused: bool


def parse_query(state: GraphState) -> GraphState:
    """Entry node. TODO: light query normalization / entity hinting."""
    return state


def node_retrieve_vector(state: GraphState, store) -> GraphState:
    state["vector_result"] = retrieval_vector.retrieve(state["query"], store)
    return state


def node_retrieve_graph(state: GraphState, store) -> GraphState:
    state["graph_result"] = retrieval_graph.retrieve(state["query"], store)
    return state


def node_confidence_gate(state: GraphState) -> GraphState:
    state["refused"] = confidence_gate.should_refuse(
        state["vector_result"], state["graph_result"]
    )
    return state


def node_generate_or_refuse(state: GraphState) -> GraphState:
    if state["refused"]:
        state["answer"] = confidence_gate.REFUSAL_MESSAGE
    else:
        # TODO: pick the higher-confidence arm, or blend both, per
        # docs/PLAN.md's per-query "expected edge" notes.
        state["answer"] = generation.generate_answer(state["query"], state["vector_result"])
    return state


def build_graph():
    """Wire the nodes above into a compiled LangGraph StateGraph.

    TODO: from langgraph.graph import StateGraph; add each node above,
    fan out parse_query -> [node_retrieve_vector, node_retrieve_graph] in
    parallel, converge both into node_confidence_gate, then branch into
    node_generate_or_refuse. Return graph.compile().
    """
    raise NotImplementedError
