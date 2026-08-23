"""Streamlit chat UI — the query surface named in the one-liner primer.

See docs/SCOPE.md: "...in a simple chat interface..." This page just wires
user input to the compiled LangGraph flow (app/graph_flow.py) and renders
the cited answer (or refusal) — no retrieval logic belongs here.
"""

import json

import streamlit as st

from app.common import config
from app.core.chunking import chunk_records
from app.core.graph_build import build_graph_store
from app.core.ingestion import RawRecord
from app.core.vector_store import HybridVectorStore
from app.graph_flow import build_graph

st.set_page_config(page_title="LangChain Org Knowledge — GraphRAG", page_icon="🕸️")
st.title("LangChain Org Knowledge")
st.caption(
    "Ask who worked on what, or what was decided and by whom, across the "
    "LangChain repo's PRs, issues, and RFCs."
)


@st.cache_resource(show_spinner="Loading corpus and building indices (first run only)...")
def _load_app():
    """Build both retrieval indices once per server process, not per
    query — ingestion output is read from disk (data/corpus/raw/, see
    app/core/ingestion.py), not re-pulled from GitHub here.
    """
    records: list[RawRecord] = []
    for fname in ("prs.jsonl", "issues_and_rfcs.jsonl"):
        path = config.RAW_CORPUS_DIR / fname
        with open(path) as f:
            for line in f:
                records.append(RawRecord(**json.loads(line)))

    chunks = chunk_records(records)
    vector_store = HybridVectorStore()
    vector_store.add_chunks(chunks)
    graph_store = build_graph_store(records)

    return build_graph(vector_store, graph_store), len(records)


try:
    app, n_records = _load_app()
except FileNotFoundError:
    st.error(
        "No ingested corpus found in `data/corpus/raw/`. Run "
        "`python -m app.core.ingestion` first (needs `GITHUB_TOKEN` in "
        "`.env`)."
    )
    st.stop()

st.caption(f"Indexed {n_records} PRs/issues/RFCs from `{config.GITHUB_REPO}`.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

query = st.chat_input("Ask a question about the LangChain repo...")
if query:
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        with st.spinner("Retrieving (both arms) and generating..."):
            result = app.invoke({"query": query})

        st.markdown(result["answer"])

        with st.expander("Retrieval details"):
            vector_result = result["vector_result"]
            graph_result = result["graph_result"]
            st.markdown(
                f"**Vector arm** — top score: `{vector_result.top_score:.3f}` "
                f"({len(vector_result.chunks)} chunks retrieved)\n\n"
                f"**Graph arm** — matched nodes: `{graph_result.matched_nodes}`\n\n"
                f"**Refused:** `{result['refused']}`"
            )

    st.session_state.messages.append({"role": "assistant", "content": result["answer"]})
