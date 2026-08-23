# 10-Query Comparison — Results & Write-up

Run against a real 200-record corpus (100 merged PRs + 100 issues/RFCs,
most-recently-updated `langchain-ai/langchain` activity as of 2026-08-21 —
pulled incrementally, see "Corpus" below) via
`app.core.evaluation.run_comparison()`. Raw output: `data/eval/results.json`.
Query set: `data/eval/test_queries.json` (each entry's `note` field explains
what it's grounded in — see "Query set" below for why it was rewritten).

## Observability KPIs

```
--- Observability KPIs ---           vector        graph
--------------------------------------------------------
queries run                              10           10
answered                                   3            2
refused                                    7            8
mean faithfulness                      0.973        0.980
mean relevance                         0.600        0.950
refusal-test accuracy                  1.000        1.000
mean latency (s)                       3.505        2.000
p95 latency (s)                       12.853       16.479
```

(`app.core.evaluation.print_kpi_summary()` — called automatically at the
end of every `run_comparison()` — produces this table for any future run.)

Faithfulness is high for both arms *when they answer* — both are well-cited
against their own retrieved evidence when they don't refuse. The real
differentiator here is **who answers at all**, not answer quality once they
do: only 5 of 10 queries got an answer from at least one arm.

## Per-query result

| # | Type | Expected | Vector | Graph | What happened |
|---|---|---|---|---|---|
| 1 | single_hop_factual | tie | refused | **answered** (1.00/1.00) | Vector's reranked score fell below threshold despite the PR being in-corpus — see "Vector arm regression" below. |
| 2 | multi_hop_relational | graph | **answered** (0.97/0.50) | refused | Flipped from expected. The query describes the PR ("resolved postponed annotations in StructuredTool") without naming a PR#/username/module literally — the graph arm's entity matcher can't find it. |
| 3 | aggregation_list | graph | refused | **answered** (0.96/0.90) | Matches expectation — graph traversal is the natural fit for "list every contributor to module X". |
| 4 | semantic_exploratory | vector | **answered** (0.97/0.95) | refused | Matches expectation cleanly — a "why does X happen" design-rationale question is exactly the vector arm's strength. |
| 5 | exact_match_lexical | vector_hybrid | refused | refused | **Unexpected refusal on both arms** — see "StreamClosedError miss" below. |
| 6 | decision_provenance | graph | **answered** (0.98/0.35) | refused | Flipped, same root cause as #2 — query describes rather than names the entity. |
| 7 | ambiguous_entity | stress_test | refused | refused | Didn't test what it was designed to — see "Ambiguous entity" below. |
| 8 | cross_document_synthesis | tie | refused | refused | Both correctly refuse but for different reasons — see original analysis (aggregation phrasing vs. no label/tag entity type). |
| 9 | out_of_corpus | must_refuse | **refused ✓** | **refused ✓** | Correct — the refusal path works. |
| 10 | plausible_but_unindexed | must_refuse | **refused ✓** | **refused ✓** | Correct — the refusal path works. |

## Findings

### 1. The graph arm's entity matcher is stricter than the query types it's expected to handle

Queries 2 and 6 both flipped from the expected "graph" edge to vector
answering instead. Root cause: `retrieval_graph._match_entities()`
(`app/core/retrieval_graph.py`) only recognizes a query as touching the
graph if it contains a literal PR/issue number (`#1234`), a contributor
username substring, or a module name substring. A query that *describes*
a PR by what it does ("the PR that resolved postponed annotations in
StructuredTool") rather than naming it gives the entity matcher nothing to
latch onto — `matched_nodes` stays 0, and the graph arm refuses even though
the answer is sitting right there in the graph.

This is a real, previously undocumented failure point, distinct from the
ones already in `docs/PLAN.md`'s table: it's not weak traversal or a bad
confidence signal, it's that **entity recognition happens before
traversal even starts**, and it's currently name/number-matching only —
no semantic entity resolution. A fix would need either an LLM-based entity
extraction pass over the query, or a hybrid: fall back to vector retrieval
to *find* the entity, then hand its ID to the graph arm for traversal.

### 2. StreamClosedError miss (query 5)

Both arms refused a query built specifically to test exact-match lexical
retrieval, despite `StreamClosedError` genuinely appearing in PRs
39325/39324's bodies (confirmed via direct grep before writing this
query). Not yet root-caused — candidates: the term may have landed in a
fenced code block that `chunking.split_prose_and_code()` isolated into a
segment whose surrounding context diluted the BM25/dense signal, or the
term may have been split across a chunk boundary. Flagged as a genuine
open failure point rather than papered over.

### 3. Ambiguous entity (query 7) didn't test what it was designed to

The rewritten query 7 targets a real entity-resolution issue in this
corpus: `ingestion.clean()` normalizes every bot-authored record's author
to `"unknown"`, so 14 unrelated `chore(model-profiles): refresh model
profile data` PRs all collapse onto one contributor node. The query asked
what that node "worked on," expecting either a nonsensical merged answer
(demonstrating the failure) or graceful disambiguation.

What actually happened: `retrieval_graph._match_entities()` explicitly
excludes `"unknown"` from contributor matching (`app/core/
retrieval_graph.py` — added specifically because "unknown" is a cleaning
placeholder, not a real entity), so the query refuses immediately. That's
arguably *better* behavior than dumping 14 unrelated PRs as one person's
work — but it means the underlying entity-collapse problem is still
latent in the graph (that merge is real and would surface the moment any
other query legitimately needed to traverse through that node) while this
particular probe can't observe it. Worth noting as a case where a
defensive design choice made earlier in the session (excluding a known
placeholder value) had a side effect on this eval.

### 4. Vector arm regression on query 1 between corpus sizes

At 40 records (an earlier run this session), "checkpointer msgpack
serialization"-style queries scored ~0.995+ against `VECTOR_CONFIDENCE_
THRESHOLD` (0.5). At 200 records / 1167 chunks, query 1 ("Who authored PR
#39832?") — a record that unambiguously exists in-corpus — refused on the
vector arm. A larger, noisier candidate pool plausibly dilutes the
reranked top score for a short, low-content chunk (a release-PR title has
little text to rerank against). Not deeply investigated here; worth a
closer look before tuning `VECTOR_CONFIDENCE_THRESHOLD` for a "final"
number, since the threshold was originally calibrated on a much smaller
corpus.

### 5. Generation was silently truncating on large subgraphs (found while wiring the Streamlit UI)

`config.GENERATION_MAX_TOKENS` was 1024 — fine at the 40-record corpus
size, but at 200 records a graph-arm aggregation answer (query 3's "list
every contributor to the agents module") got cut off mid-word
(`[contributor:ccur`). Caught by actually driving the wired-up app end to
end (`app/Home.py`) and screenshotting a real answer, not just checking
`refused`/scores — a truncated-but-non-empty answer doesn't trip any of
the existing checks. Fixed by raising `GENERATION_MAX_TOKENS` to 4096;
re-verified the same query now completes naturally and self-reports its
own completeness caveat ("this list is limited to the supplied
subgraph..."). Re-ran the full 10-query comparison after the fix — the
numbers above are post-fix; no query flipped between answered/refused,
but faithfulness/relevance on the already-answered queries improved
slightly now that nothing is cut off mid-thought.

### 6. A real scoring bug was caught and fixed mid-run

The first full run at this corpus size returned mean faithfulness 0.320
(vector) / 0.485 (graph) despite manual inspection showing well-cited,
clearly-grounded answers. Root cause: `evaluation._judge()`'s
`max_tokens=200` didn't leave headroom for Claude Opus 5's adaptive
thinking, which shares the same token budget as the visible `SCORE:` line
— intermittently truncating the response before it reached the score,
silently falling through to the "no match" 0.0 default. Confirmed by
replaying the same judge call twice and getting a thinking block once, a
plain-text answer the other time. Fixed by raising `max_tokens` to 1024
and setting `output_config={"effort": "low"}` (grading is a simple task,
per the model's own guidance). Re-verified against the real retrieved
context for the two queries that triggered it (0.95, 0.97 — matching
manual read) before re-running the full comparison.

## Corpus

Pulled incrementally, checking GitHub rate limit and query/corpus term
coverage after each step, per explicit instruction this session:

| Step | PR_LIMIT / ISSUE_LIMIT | Records | Time | Rate limit |
|---|---|---|---|---|
| 1 | 20 / 20 | 40 | 123s | comfortable |
| 2 | 50 / 50 | 100 | 123s | comfortable |
| 3 | 100 / 100 | 200 | 251s | comfortable |

Coverage plateaued at step 3 for terms tied to fabricated specifics (a
literal PR number, a contributor named "Alex", an invented error code) —
confirming further scaling wouldn't help those, which is why the query set
was rewritten instead of scaled further. `config.py`'s `PR_LIMIT`/
`ISSUE_LIMIT` defaults remain 20/20 for fast dev iteration; this eval run
used a one-off larger pull via env override (`PR_LIMIT=100 ISSUE_LIMIT=100
python -m app.core.ingestion`), not a change to those defaults.

## Query set

The original 10 queries were written as generic templates before any
corpus was pulled. A pre-run check found 9 of 10 reference terms (PR
#4213, "memory leak" *as a reviewed PR*, "retrievers module", "conversation
buffer", `ECONNRESET`, "retriever interface", a contributor named "Alex")
had zero or near-zero grounding in the real data. Queries 1-7 were rewritten
against real corpus content (see each entry's `note` field in
`data/eval/test_queries.json` and the updated table in `docs/PLAN.md`);
8-10 already worked as originally written.

## Bottom line for the deliverable

With a grounded query set, the comparison now shows real signal:

- **Graph wins outright** on the query type it's supposed to (aggregation,
  query 3) and on a factual lookup once it has an unambiguous ID to seize
  on (query 1).
- **Vector wins outright** on semantic/exploratory reasoning (query 4), as
  predicted, and also picked up two queries that were *expected* to favor
  graph (2, 6) purely because the graph arm's entity matcher couldn't
  recognize the entity from a descriptive query — a real, documented
  limitation rather than the graph arm losing on merits.
- **The refusal path works** — both correct-refusal tests (9, 10) pass on
  both arms.
- **Two open items remain before this is "done"**: the StreamClosedError
  miss (finding 2) isn't root-caused, and the vector-arm threshold
  (finding 4) was calibrated on a much smaller corpus and may need
  retuning now.
