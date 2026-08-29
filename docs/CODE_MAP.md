# Code Map — Week 2 Project

A file-by-file index of what each source file does, at a glance. For the
full architecture and reasoning, see [PLAN.md](PLAN.md); for the head-to-head
results, see [COMPARISON_ANALYSIS.md](COMPARISON_ANALYSIS.md) and
[EVAL_RESULTS.md](EVAL_RESULTS.md).

This project runs two retrieval arms — hybrid vector-RAG and GraphRAG — over
the same corpus (the LangChain GitHub repo: PRs, issues, RFCs, module docs)
and compares them head-to-head on the same query set, orchestrated by a
LangGraph state machine with a refuse-vs-generate confidence gate.

---

## `app/` — application code

### Entry point & orchestration

| File | What it does |
|---|---|
| [`app/Home.py`](../app/Home.py) | The Streamlit chat UI — the only query surface. Wires user input straight into the compiled LangGraph flow and renders the cited answer (or refusal); deliberately contains no retrieval logic of its own. |
| [`app/graph_flow.py`](../app/graph_flow.py) | Builds the LangGraph state machine: `parse_query → {retrieve_vector, retrieve_graph} → confidence_gate → {generate, refuse}`. This is the actual mechanism the interactive app runs each query through. (The eval harness in `evaluation.py` calls the vector/graph/generation modules directly per arm instead, since it needs both arms' answers side by side rather than one merged answer.) |

### Shared helpers (`app/common/`)

| File | What it does |
|---|---|
| [`app/common/config.py`](../app/common/config.py) | Central project-wide settings (model names, chunk sizes, top-k, thresholds) — every module reads from here instead of scattering literal values. |
| [`app/common/llm_client.py`](../app/common/llm_client.py) | Placeholder for a thin shared LLM-provider wrapper. Not implemented — `app/core/generation.py` currently calls the Anthropic SDK directly. |
| [`app/common/styling.py`](../app/common/styling.py) | Placeholder for shared Streamlit styling/theme helpers, in the spirit of the Week 1 project's `common/styling.py` + `theme.py`. Not implemented. |

### Core pipeline (`app/core/`)

| File | What it does |
|---|---|
| [`app/core/ingestion.py`](../app/core/ingestion.py) | Pulls PRs, issues, and RFC threads from the GitHub API (`langchain-ai/langchain`) via `pull_pull_requests()`/`pull_issues_and_rfcs()`, keeping structured metadata (author, reviewers, linked issues, merge date, module path) the graph is built from later. Writes raw records to `data/corpus/raw/` (gitignored — regenerate by re-running this module). |
| [`app/core/chunking.py`](../app/core/chunking.py) | Splits cleaned corpus text into chunks sized to match the embedding model's capacity (~200–300 tokens for the default 384-dim model). Chunks code blocks separately from prose, since exact identifiers inside code are what dense retrieval is weakest at. |
| [`app/core/embeddings.py`](../app/core/embeddings.py) | Placeholder for the embed-chunks/embed-queries interface. Not implemented — embedding happens inline in `vector_store.py`. |
| [`app/core/vector_store.py`](../app/core/vector_store.py) | `HybridVectorStore` — dense embeddings (local sentence-transformers by default, no API key required) fused with a BM25 sparse index via reciprocal rank fusion, so exact identifiers (PR numbers, usernames, error codes) aren't lost to pure semantic search. |
| [`app/core/retrieval_vector.py`](../app/core/retrieval_vector.py) | The vector-RAG arm: hybrid retrieve from `HybridVectorStore`, then a cross-encoder reranks the merged top ~20 down to the top 5 chunks that reach the LLM. |
| [`app/core/graph_build.py`](../app/core/graph_build.py) | Extracts entities (contributors, PRs, issues/RFCs, modules, skills) and relationships (authored, reviewed, merged, discusses, decided-in, uses) from the cleaned corpus into a `GraphStore`. "Skills" are recovered from conventional-commit scopes and known libraries. |
| [`app/core/retrieval_graph.py`](../app/core/retrieval_graph.py) | The GraphRAG arm: match query entities against the graph, traverse 1–2 hops, serialize the resulting subgraph as retrieval context. |
| [`app/core/confidence_gate.py`](../app/core/confidence_gate.py) | `should_refuse()` — a real branch in the LangGraph state machine (not just a prompt instruction) that decides refuse-vs-generate per arm, designed before the happy path so an empty/weak retrieval never silently gets a hallucinated answer. |
| [`app/core/generation.py`](../app/core/generation.py) | Calls Claude (Anthropic SDK) with retrieved context from either arm to produce a grounded, cited answer — every claim should trace back to a specific chunk (vector arm) or node/edge (graph arm), which is what `evaluation.py`'s faithfulness score checks. |
| [`app/core/evaluation.py`](../app/core/evaluation.py) | Runs both arms against the 10-query comparison set (`data/eval/test_queries.json`) and LLM-judges each answer on faithfulness, relevance, correct-refusal-rate, and latency. `run_comparison()` and `summarize_results()` produce the numbers the write-up is based on. |
| [`app/core/checkpoints.py`](../app/core/checkpoints.py) | Fast, cheap sanity checks (`check_ingestion`, `check_chunking`, `check_vector_store`, ... `check_generation`) run between pipeline stages, each modeled on a real bug found the hard way (missing PR-number embedding, Chroma's batch-size limit, generation's token budget exhausted by thinking, a corpus/query-set mismatch — see `EVAL_RESULTS.md`). Catches the same class of failure in seconds instead of after a full ~20-call LLM-judged comparison run. |

---

## `data/` — corpus and eval assets

| Path | What it is |
|---|---|
| [`data/corpus/README.md`](../data/corpus/README.md) | Describes the corpus directory's purpose and provenance notes. |
| `data/corpus/raw/issues_and_rfcs.jsonl`, `data/corpus/raw/prs.jsonl` | Raw ingested records from `ingestion.py` — real GitHub data (langchain-ai/langchain), not synthetic. |
| [`data/eval/README.md`](../data/eval/README.md) | Describes the eval-set directory's purpose. |
| `data/eval/test_queries.json` | The 10-query comparison set `evaluation.py` runs both arms against. |
| `data/eval/results.json` | Saved output of the last `run_comparison()` run — the raw numbers behind `EVAL_RESULTS.md`/`COMPARISON_ANALYSIS.md`. |

---

## `docs/` — design, results, and write-up docs

| File | What it does |
|---|---|
| [`docs/SCOPE.md`](SCOPE.md) | The project's scope definition: use case, corpus choice, required node/edge types for the graph schema. |
| [`docs/PLAN.md`](PLAN.md) | Full architecture and reasoning — the source of truth most other modules' docstrings point back to (chunk sizing, why the vector arm is hybrid, the refusal-path design, eval methodology). Also published as an interactive artifact. |
| [`docs/EVAL_RESULTS.md`](EVAL_RESULTS.md) | The full investigation log against the real 1000-record corpus: every bug found, its root cause, and the fix — what `checkpoints.py`'s checks are each modeled on. |
| [`docs/COMPARISON_ANALYSIS.md`](COMPARISON_ANALYSIS.md) | A focused, presentation-oriented summary of how the two arms compare head-to-head. |
| [`docs/PROJECT_WRITEUP.md`](PROJECT_WRITEUP.md) | The submission write-up. |
| [`docs/DEMO_SCRIPT.md`](DEMO_SCRIPT.md) | A ~4–5 minute demo walkthrough script, each query chosen to demonstrate one specific behavior. |
| [`docs/GITHUB_SETUP.md`](GITHUB_SETUP.md) | One-time steps for connecting the local repo to GitHub. |
| [`docs/assets/architecture.png`](assets/architecture.png) | Architecture diagram referenced from `PLAN.md`/`README.md`. |
| `docs/*.docx` | Word-format copies of the corresponding `.md` write-ups, for submission. |

---

## Top-level files

| File | What it does |
|---|---|
| [`README.md`](../README.md) | Project overview, architecture summary, links to all the docs above. |
| [`CHANGELOG.md`](../CHANGELOG.md) | Project change history. |
| [`requirements.txt`](../requirements.txt) | Python dependencies (LangGraph, LangChain, Anthropic SDK, sentence-transformers, rank-bm25, a cross-encoder reranker, Streamlit, etc.). |
| [`run.sh`](../run.sh) | Local launch script. |
| [`runtime.txt`](../runtime.txt) | Pinned Python runtime version for hosted deploy. |
| [`.env.example`](../.env.example) | Template for required env vars (`ANTHROPIC_API_KEY`, GitHub token for ingestion, etc.). |
| [`screenshots/`](../screenshots/) | App screenshots for the write-up. |
