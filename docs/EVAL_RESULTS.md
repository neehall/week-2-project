# 10-Query Comparison — Results & Write-up

Run against the real ingested corpus (20 PRs + 20 issues/RFCs, most-recently-
updated `langchain-ai/langchain` activity as of 2026-08-21 — see
`data/corpus/raw/`) via `app.core.evaluation.run_comparison()`. Raw output:
`data/eval/results.json`.

## Headline result: 20/20 refused

Every query, on both arms, refused. Score breakdown:

| Query | Type | Expected edge | Vector | Graph |
|---|---|---|---|---|
| 1 | single_hop_factual | tie | refused | refused |
| 2 | multi_hop_relational | graph | refused | refused |
| 3 | aggregation_list | graph | refused | refused |
| 4 | semantic_exploratory | vector | refused | refused |
| 5 | exact_match_lexical | vector_hybrid | refused | refused |
| 6 | decision_provenance | graph | refused | refused |
| 7 | ambiguous_entity | stress_test | refused | refused |
| 8 | cross_document_synthesis | tie | refused | refused |
| 9 | out_of_corpus (refusal test) | must refuse | **refused ✓** | **refused ✓** |
| 10 | plausible_but_unindexed (refusal test) | must refuse | **refused ✓** | **refused ✓** |

**This is not a meaningful vector-vs-graph comparison.** It's a corpus
coverage failure, and it was predicted before running: the 10 queries were
written as generic templates (PR #4213, "memory leak", "retrievers module",
"conversation buffer", `ECONNRESET`, "retriever interface", a contributor
named "Alex") before any real data was pulled. A pre-run check confirmed 9 of
10 reference terms have **zero occurrences** in the actual 40-record corpus
— only "streaming" (query 8) appears at all (3 hits).

Queries 9-10 are the only two that "pass" in the sense of testing what they
were designed to test — they're deliberately out-of-corpus, and both arms
correctly refused rather than hallucinating. That's a real, if narrow,
positive result: **the refusal path works.**

## A real finding hiding in the noise: query 8

Query 8 ("Summarize the discussion across all issues tagged `streaming`")
is the one case where relevant content *does* exist in the corpus (3 issues:
#38074, #35436, #39333), yet both arms still refused — for different reasons
that are each individually correct given their own design:

- **Vector arm**: the reranked top score fell below
  `VECTOR_CONFIDENCE_THRESHOLD` (0.5) — the query's phrasing ("all issues
  tagged X") doesn't closely match any single chunk's content, since no
  chunk *is* a tag-aggregation summary.
- **Graph arm**: `retrieval_graph._match_entities()` only recognizes PR/issue
  numbers, contributor usernames, and module names (`app/core/
  retrieval_graph.py`) — it has no concept of an issue *label* like
  "streaming" as an entity type, so `matched_nodes` is always 0 for a
  tag-based query regardless of corpus content.

This is a legitimate instance of two failure points already flagged in
`docs/PLAN.md`'s "Failure points to test for" table: the graph arm's
entity-matching is narrower than the query types it's expected to handle
(no label/tag node type exists in the schema), and aggregation-style queries
in general are exactly where a small, template-matched chunk set struggles
without either a wider retrieval net or genuine multi-document synthesis.

## Why this happened

`PR_LIMIT`/`ISSUE_LIMIT` default to 20 (dropped from 100 during the
ingestion-hang fix, see CHANGELOG) and pull the *most recently updated*
records — a narrow, recent slice of a very large, long-lived repo. The
10-query set was written against no actual data (a reasonable template at
plan time), and was never reconciled against what ingestion actually pulled
before this run.

## What this means for the deliverable

The pipeline mechanics are proven — ingestion, chunking, both retrieval
arms, the confidence gate, generation, and the full LangGraph wiring have
each been verified independently against real data (see CHANGELOG, commits
`ba6522b` through the graph_flow commit). What's *not* yet demonstrated is
the actual vector-vs-graph comparison the project is about, because the
query set and the corpus don't overlap.

Two ways to fix this, not done in this pass (explicitly deferred — see
conversation): rewrite the 10 queries to match the real 40-record corpus,
or pull a larger/targeted corpus so the existing queries have a chance of
landing. Either one is a prerequisite for a real comparison write-up.
