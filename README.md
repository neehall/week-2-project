# GraphRAG for Organizational Knowledge (Week 2 Project)

Two retrieval arms — hybrid vector-RAG and GraphRAG — run over the same
corpus (the LangChain GitHub repo: PRs, issues, RFCs, module docs) and are
compared head-to-head on the same 10 queries, so the difference between
"semantic similarity" and "structured relationships" is measured, not just
asserted.

Status: skeleton only. Architecture and eval plan are done; nothing is
implemented yet.

Full architecture, diagrams, and reasoning: **[Two Arms, One Corpus](docs/PLAN.md)**
(also published as an interactive artifact — see `docs/PLAN.md` for the link).

## One-liner

> My RAG app helps open-source contributors and maintainers answer "who
> worked on what, and what decisions were made and by whom" questions from
> the LangChain GitHub repo's contributors, PRs, issues, and RFCs, in a
> simple chat interface, with 90% faithfulness.

## Prerequisites

- Python 3.10+
- A Neo4j instance (local Docker or Aura free tier) — or NetworkX for a
  purely in-memory graph if you'd rather skip the Neo4j setup
- Nebius (or OpenAI-compatible) API credentials for embeddings + generation
- A GitHub personal access token (read-only, for pulling PRs/issues via API)

## Install & run

```bash
python3 -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill in API keys
```

```bash
./run.sh
```

## Project structure

```
app/
  Home.py                  # Streamlit chat UI — the query surface
  graph_flow.py             # LangGraph state machine wiring both arms + the confidence gate
  core/
    ingestion.py              # pull PRs / issues / RFCs / module docs from the GitHub API
    chunking.py                # chunk cleaned text, sized to the embedding model's capacity
    graph_build.py               # extract entities/relationships, build the 20+ node graph
    vector_store.py                # dense embeddings + BM25 index, fused
    retrieval_vector.py              # hybrid retrieve -> rerank -> top-5 (vector-RAG arm)
    retrieval_graph.py                 # entity match -> 1-2 hop traversal (GraphRAG arm)
    confidence_gate.py                   # decides refuse vs. generate, per arm
    generation.py                          # LLM call, grounded + cited
    evaluation.py                            # faithfulness / relevance / refusal-rate / latency scoring
data/
  corpus/                   # raw + cleaned pulled GitHub data
  eval/
    test_queries.json         # the 10-query comparison set (incl. 2 refusal-test queries)
docs/
  PLAN.md                   # full architecture + eval plan (source of truth)
  SCOPE.md                  # corpus choice, primer, and the filled-out framework
screenshots/                # visual verification, once there's a UI to capture
```

## Design patterns implemented

- [ ] Ingestion — GitHub API pull + cleaning
- [ ] Vector-RAG arm — hybrid (dense + BM25) retrieval, cross-encoder rerank
- [ ] GraphRAG arm — entity match + 1-2 hop graph traversal
- [ ] Confidence gate — refuse vs. generate, designed before the happy path
- [ ] LangGraph orchestration — `parse_query -> {retrieve_vector, retrieve_graph} -> confidence_gate -> {generate, refuse}`
- [ ] 10-query eval harness + comparison report

## Data provenance

Corpus: the public LangChain GitHub repo (`langchain-ai/langchain`) —
contributors, PRs, issues, RFC discussions, and module docs, pulled via the
GitHub REST/GraphQL API. Public data, no PII beyond public GitHub usernames.

## Vector store / graph store

- Vector store: Chroma (local, no server required) — swap for FAISS if
  preferred
- Sparse index: `rank_bm25`
- Graph store: Neo4j (or NetworkX for a no-server alternative — see
  `app/core/graph_build.py`)
