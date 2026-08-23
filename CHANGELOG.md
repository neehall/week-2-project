# Changelog

All notable changes to this project are logged here, newest first. This is
the versioning record for the project — `docs/PLAN.md` and `docs/SCOPE.md`
are the living design docs; this file tracks what changed and when.

## [Unreleased]

### Added
- `app/core/chunking.py` — implemented: `split_prose_and_code()` splits a
  cleaned record body on fenced ``` blocks (same convention as
  `ingestion.clean()`); `chunk_record()` token-splits each segment via
  `RecursiveCharacterTextSplitter.from_tiktoken_encoder` sized by
  `chunk_tokens`, prepends the record title to the lead-in prose segment,
  and assigns each `Chunk` a `chunk_id`; `chunk_records()` batches this
  over a list of records. Verified end-to-end against a live 20-PR +
  20-issue ingestion pull (152 chunks from 40 records).
- `docs/PLAN.md` — "Failure points to test for" section: entity
  resolution, relationship extraction quality, traversal scope, subgraph
  serialization, staleness, weak graph-arm confidence signal, and losing
  to vector-RAG on purely semantic queries — each mapped to a specific
  eval-set query to test it against.
- `app/common/config.py` / `app/core/ingestion.py` — ingestion reliability
  fixes after a run hung for 30+ min: `config.py` now actually calls
  `load_dotenv()` (was a listed dependency but never invoked, so `.env`
  was silently ignored); GitHub client now sets a request timeout + retry
  count instead of hanging on a stalled connection; both pull functions
  enforce a wall-clock time budget (`INGESTION_TIME_BUDGET_SECONDS`,
  default 120s) independent of record limits and print progress every 10
  records; `PR_LIMIT`/`ISSUE_LIMIT` defaults dropped 100 -> 20
  (env-overridable) so dev iteration doesn't require a full pull. Verified
  end-to-end: 20 PRs + 20 issues in 52s (was 30+ min unauthenticated).
- `app/common/config.py` — filled in: repo/paths, chunk size (500 tokens,
  midpoint of docs/PLAN.md's 400-600 range), top-k, confidence threshold,
  env var names.
- `app/core/ingestion.py` — implemented: pulls merged PRs and substantive
  issues/RFCs from `langchain-ai/langchain` via PyGithub, resolves
  reviewers/linked-issues/dominant-module-path per record, strips bot
  noise and HTML comments in `clean()` without touching fenced code
  blocks, writes `data/corpus/raw/{prs,issues_and_rfcs}.jsonl`. Verified
  against the live API with a `GITHUB_TOKEN` in `.env`.
- Initial project scaffold: `README.md`, `requirements.txt`, `.env.example`,
  `run.sh`, `.gitignore`.
- `docs/SCOPE.md` — corpus choice, one-liner primer, filled-out framework.
- `docs/PLAN.md` — architecture, chunking/embedding sizing, hybrid retrieval
  design, refusal path, 10-query comparison set, eval methodology, build
  sequence. Full interactive version published as a Claude artifact (linked
  in the doc).
- `app/core/` module skeletons: ingestion, chunking, graph_build,
  vector_store, retrieval_vector, retrieval_graph, confidence_gate,
  generation, evaluation.
- `app/graph_flow.py` — LangGraph state machine skeleton wiring both
  retrieval arms through the confidence gate.
- `data/eval/test_queries.json` — the 10-query comparison set.
