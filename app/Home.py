"""Streamlit chat UI — the query surface named in the one-liner primer.

See docs/SCOPE.md: "...in a simple chat interface..." This page just wires
user input to the compiled LangGraph flow (app/graph_flow.py) and renders
the cited answer (or refusal) — no retrieval logic belongs here.
"""

import streamlit as st

st.set_page_config(page_title="LangChain Org Knowledge — GraphRAG", page_icon="🕸️")
st.title("LangChain Org Knowledge")
st.caption(
    "Ask who worked on what, or what was decided and by whom, across the "
    "LangChain repo's PRs, issues, and RFCs."
)

# TODO: from app.graph_flow import build_graph; cache the compiled graph
# with st.cache_resource so it's built once per session, not per query.

query = st.chat_input("Ask a question about the LangChain repo...")
if query:
    with st.chat_message("user"):
        st.write(query)
    with st.chat_message("assistant"):
        st.write("Not wired up yet — see app/graph_flow.py's TODOs.")
