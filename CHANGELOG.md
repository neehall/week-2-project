# Changelog

All notable changes to this project are logged here, newest first. This is
the versioning record for the project — `docs/PLAN.md` and `docs/SCOPE.md`
are the living design docs; this file tracks what changed and when.

## [Unreleased]

### Changed
- Corpus pulled incrementally from 40 -> 100 -> 200 records (checking
  GitHub rate limit and eval-query term coverage at each step, per
  explicit instruction), via one-off `PR_LIMIT=100 ISSUE_LIMIT=100`
  env-override runs — `config.py`'s 20/20 dev defaults are unchanged.
- `data/eval/test_queries.json` / `docs/PLAN.md` — rewrote 7 of the 10
  comparison queries to ground them in the real corpus (each entry's
  `note` field explains what it's grounded in). Query 7 was repurposed
  from a hypothetical name-collision stress test to a real one this
  corpus exhibits: `ingestion.clean()` normalizes every bot-authored
  record's author to `"unknown"`, so 14 unrelated automated PRs collapse
  onto one contributor node.
- `app/core/evaluation.py` — added `summarize_results()` /
  `print_kpi_summary()`: a side-by-side vector-vs-graph observability KPI
  table (queries run/answered/refused, mean faithfulness/relevance,
  refusal-test accuracy, mean/p95 latency), called automatically at the
  end of every `run_comparison()` run.
- `app/core/evaluation.py` — fixed a real scoring bug: `_judge()`'s
  `max_tokens=200` didn't leave headroom for Claude Opus 5's adaptive
  thinking, which shares the same token budget as the visible `SCORE:`
  line — intermittently truncating the judge's response before it wrote
  the score and silently falling through to a 0.0 default even for
  well-cited, clearly-grounded answers. First full run showed mean
  faithfulness 0.320/0.485 despite manual inspection showing the
  opposite; fixed by raising `max_tokens` to 1024 and setting
  `output_config={"effort": "low"}`, re-verified against real retrieved
  context before re-running.
- `docs/EVAL_RESULTS.md` — full rewrite with the real comparison: 5 of 10
  queries got an answer from at least one arm (up from 0 before the
  corpus/query fixes). Findings: the graph arm's entity matcher requires
  a query to literally name a PR#/username/module rather than describe
  it, flipping 2 expected-graph queries to vector; an unresolved
  `StreamClosedError` exact-match miss on both arms; the "unknown"
  entity-collapse query refused rather than demonstrating the merge
  (the matcher's earlier "unknown" exclusion is a defensive design
  choice that also masks this probe); and a likely vector-threshold
  regression at the larger corpus size worth re-tuning.

### Added
- `app/core/evaluation.py` — implemented: `score_faithfulness()` and
  `score_relevance()` are single-call Claude LLM-judge scores (0.0-1.0,
  parsed from a `SCORE: <n>` line); `run_comparison()` runs the 10-query
  set through both arms independently — each arm applies its own refusal
  rule (vector: top score below threshold; graph: no matched nodes)
  rather than `confidence_gate`'s combined OR, since the point here is
  comparing each arm's own behavior, not the merged app-facing decision.
  `generation.py`'s client accessor renamed `_get_client` ->
  `get_client()` (public) so evaluation.py can reuse the same client
  instance instead of opening a second one.
- `docs/EVAL_RESULTS.md` / `data/eval/results.json` — ran the real
  10-query set (`data/eval/test_queries.json`) against the real 40-record
  corpus end-to-end. Result: **all 20 arm-runs (10 queries x 2 arms)
  refused** — not a meaningful vector-vs-graph comparison, and predicted
  before running: 9 of the 10 queries reference terms (PR #4213, "memory
  leak", "retrievers module", a contributor named "Alex", etc.) that were
  written as generic templates before any corpus was pulled and have zero
  occurrences in the actual data. Queries 9-10 (deliberately
  out-of-corpus) correctly refused on both arms — the refusal path
  itself works. Query 8 ("streaming") is the one case where matching
  content does exist (3 issues) yet both arms still refused, for two
  different legitimate reasons: the vector arm's reranked score fell
  below threshold on the aggregation-style phrasing, and the graph arm's
  entity matcher has no concept of an issue *label* as an entity type —
  a real instance of failure points already flagged in docs/PLAN.md.
  Full write-up and root cause in docs/EVAL_RESULTS.md. Fixing the
  query/corpus mismatch (rewriting the queries or widening ingestion) is
  explicitly deferred, not done in this pass.
- `app/graph_flow.py` — implemented: wires `parse_query -> {retrieve_vector,
  retrieve_graph} -> confidence_gate -> generate_or_refuse` as a compiled
  LangGraph `StateGraph`. `build_graph(vector_store, graph_store)` binds
  the stores into their retrieval nodes via `functools.partial` (node
  functions only receive `(state, [config])` at invoke time). Two
  LangGraph gotchas hit and fixed: a node parameter literally named
  `store` collides with LangGraph's own `BaseStore` dependency injection
  and gets silently overwritten with `None` — renamed to
  `vector_store`/`graph_store`; and nodes must return only the state keys
  they update (not the whole state dict), since two parallel branches
  each "writing" an unrelated key they didn't change looks like a
  conflicting concurrent update to LangGraph's channel model.
  `generate_or_refuse` prefers the vector arm when it clears its own
  threshold (a graded score) and falls back to the graph arm otherwise
  (`matched_nodes` is a coarser binary signal). Verified end-to-end: a
  factual query answers correctly off the vector arm, an out-of-corpus
  query refuses, and a relational "what did X work on" query — where the
  vector arm's score collapses to ~0 but the graph arm still has a
  matched entity — correctly falls back to the graph arm, a concrete
  instance of the graph-wins pattern docs/PLAN.md's query-type table
  predicts.
- `app/core/generation.py` — implemented: calls Claude via the official
  `anthropic` SDK (`config.GENERATION_MODEL`, default `claude-opus-5`),
  swapped in for the originally-scoped Nebius-hosted model since
  `NEBIUS_API_KEY` isn't set — needs `ANTHROPIC_API_KEY` in `.env`
  instead. `_format_context()` renders either arm's retrieval result as
  citable text (chunk_id-tagged for the vector arm, the graph arm's
  already-serialized subgraph as-is); the system prompt requires an
  inline citation on every factual claim and an explicit "context
  doesn't support this" instead of guessing. Verified end-to-end against
  both arms with a real `ANTHROPIC_API_KEY`: the vector arm produced a
  grounded, per-claim-cited answer from real issue chunks and correctly
  flagged what the retrieved context couldn't answer; the graph arm
  produced a correctly-cited summary of a contributor's PRs from the
  serialized subgraph.
- `app/core/graph_build.py` / `retrieval_graph.py` — graph arm implemented
  end-to-end on a NetworkX in-memory backend (no server needed;
  `GraphStore(backend="neo4j")` documented as a TODO for later).
  `extract_entities_and_relations()` builds contributor/pr/issue/rfc/module
  nodes and authored/reviewed/merged/decided_in/discusses edges straight
  from the structured metadata PyGithub already gave us (no LLM
  extraction needed for this pass) — issues/RFCs don't get a
  file-diff-derived `module_path` from ingestion, so `_infer_module_path()`
  falls back to keyword-matching the record text against the vocabulary
  of module names seen in the PRs. `retrieval_graph.retrieve()`
  entity-matches PR/issue numbers, contributor usernames, and module
  names out of the query text, then traverses `max_hops` via
  `GraphStore.ego_subgraph()` and serializes the result to text.
  Verified against the real 40-record corpus: 77 nodes (well past the
  20+ requirement), correct multi-hop traversal from a contributor to
  their PRs/reviewers/modules, and `matched_nodes == 0` on an
  out-of-corpus query — confirmed both arms feed `confidence_gate` and
  answer/refuse correctly on the same two test queries.
- `app/core/vector_store.py` / `retrieval_vector.py` / `confidence_gate.py`
  — vector arm implemented end-to-end: `HybridVectorStore` wraps a Chroma
  dense collection + a `rank_bm25.BM25Okapi` sparse index over the same
  chunks, fused via `reciprocal_rank_fusion`; `retrieve()` reranks the
  fused top ~20 with a `cross-encoder/ms-marco-MiniLM-L-6-v2`
  cross-encoder, sigmoid-normalizing its raw logit output to a 0-1 score
  comparable against `confidence_gate`'s threshold; `confidence_gate.py`
  now reads its threshold/message from `config.py` instead of a
  duplicate hardcoded constant that had drifted (0.65 vs. 0.5).
  Embedding model switched to a local `all-MiniLM-L6-v2`
  (sentence-transformers, no API key needed) rather than the
  Nebius-hosted default, with chunk size dropped 500 -> 250 tokens to
  match its 384 dims per docs/PLAN.md's capacity table; swap back once
  `NEBIUS_API_KEY` is set. Verified against the real 40-record/202-chunk
  corpus: paraphrased in-corpus queries score ~0.995-0.999, out-of-corpus
  queries score ~0.0003-0.11, and the gate correctly answers one and
  refuses the other.
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
