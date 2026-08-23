# GraphRAG vs. Vector-RAG — Comparison Analysis

A focused, presentation-oriented summary of how the two retrieval arms
compare on the same 10 questions. For the full investigation log —
bugs found, root causes, and how each number was arrived at — see
`docs/EVAL_RESULTS.md`. Raw data: `data/eval/results.json` and
`data/eval/test_queries.json`.

## Methodology

Every query runs through both arms independently and is scored the same
way, so the comparison is apples-to-apples:

![Architecture diagram](assets/architecture.png)

- **Corpus:** 200 real records (100 merged PRs + 100 issues/RFCs) pulled
  live from `langchain-ai/langchain` via the GitHub API — not synthetic.
- **Graph:** 324 nodes (contributor, PR, issue, module, skill), well past
  the 20-node minimum.
- **Each arm applies its own refusal rule**, independently: vector
  refuses when its reranked confidence score falls below threshold;
  graph refuses when no entity in the query matches a graph node. This
  is deliberately *not* the same as the merged app-facing decision
  (`app/graph_flow.py`'s `confidence_gate`, which answers if *either* arm
  is confident) — the point here is to see each arm's own behavior in
  isolation.
- **Scoring:** faithfulness (does every claim trace to the retrieved
  evidence?) and relevance (does the evidence address the question?),
  both LLM-judged 0.0-1.0; refusal-test accuracy on the two queries
  specifically designed to require a refusal.

## Results

```
--- Observability KPIs ---           vector        graph
--------------------------------------------------------
queries run                              10           10
answered                                   5            2
refused                                    5            8
mean faithfulness                      0.990        0.985
mean relevance                         0.640        0.950
refusal-test accuracy                  1.000        1.000
mean latency (s)                       4.285        1.978
p95 latency (s)                       11.103       17.241
```

**6 of the 10 queries get a real answer from at least one arm.** The
other 4 either correctly refuse (2 refusal-test queries, by design) or
expose a specific, documented limitation rather than a general failure
(see `docs/EVAL_RESULTS.md` findings 2, 3, 6).

## Side-by-side per query

| # | Question type | Question | Vector | Graph | Winner |
|---|---|---|---|---|---|
| 1 | Single-hop factual | Who authored PR #39832? | ✅ answered | ✅ answered | **Tie** |
| 2 | Multi-hop relational | Who reviewed the PR that resolved postponed annotations in StructuredTool, and what module does it touch? | ✅ answered | ❌ refused | **Vector** |
| 3 | Aggregation / list | List every contributor to the agents module. | ❌ refused | ✅ answered | **Graph** |
| 4 | Semantic / exploratory | Why do shell subprocess resources leak when a run is interrupted mid-session? | ✅ answered | ❌ refused | **Vector** |
| 5 | Exact-match / lexical | Which PR references StreamClosedError? | ✅ answered | ❌ refused | **Vector** |
| 6 | Decision provenance | What was decided about adding standard model exception types, and who approved it? | ✅ answered | ❌ refused | **Vector** |
| 7 | Ambiguous entity | What has the "unknown" contributor been working on recently? | ❌ refused | ❌ refused | Neither (by design — see below) |
| 8 | Cross-document synthesis | Summarize the discussion across all issues tagged streaming. | ❌ refused | ❌ refused | Neither (known limitation) |
| 9 | Out-of-corpus | Who approved LangChain's pricing model? | ✅ refused | ✅ refused | **Tie (correct refusal)** |
| 10 | Plausible but unindexed | What did the team decide about the Rust rewrite? | ✅ refused | ✅ refused | **Tie (correct refusal)** |

## When structured relationships beat semantic similarity — and vice versa

**Graph wins outright on aggregation (query 3).** "List every contributor
to the agents module" has no single passage that *is* the answer — it
requires walking every PR/issue linked to a module and collecting who
touched them. No amount of dense or sparse retrieval over independent
text chunks can assemble that; it's a graph traversal by nature, and the
graph arm handles it cleanly (a full contributor table, correctly
sourced from `authored`/`reviewed`/`merged` edges).

**Vector wins outright on semantic/exploratory reasoning (query 4).**
"Why do shell subprocess resources leak when interrupted mid-session?" is
a design-rationale question with a real, discursive answer sitting in one
GitHub issue's discussion thread. There's no graph relationship to
traverse — no node encodes "the reason a leak happens" — so this is
squarely a dense-retrieval strength: find the passage that's semantically
about the question and let generation synthesize it.

**The two "expected graph" queries that flipped (2, 6) reveal the graph
arm's real constraint: it needs to be told exactly who or what to look
up.** Both describe a PR by what it accomplished rather than naming it
directly. The graph arm's entity matcher only recognizes literal PR/issue
numbers, contributor usernames, or module names in the query text — a
paraphrased reference gives it nothing to seize on, so traversal never
starts even though the graph holds the answer. Vector retrieval doesn't
have this problem because it matches on meaning, not identifiers — which
is exactly the "structured relationships vs. semantic similarity"
trade-off this project set out to measure, just running in the direction
that wasn't originally predicted for these two queries.

**The refusal path is symmetric and correct.** Queries 9 and 10 are
deliberately unanswerable from this corpus, and both arms refuse rather
than fabricate a plausible-sounding answer — the more expensive failure
mode a RAG system can have. This was verified under real stress too: a
skill-vocabulary change briefly caused a false-positive match on query 9
(see `docs/EVAL_RESULTS.md` finding 6) and was caught and fixed before
being reported as a clean result.

## Bottom line

The comparison shows real, query-type-dependent signal rather than one
architecture uniformly beating the other:

- **Graph is the right tool** for aggregation/list queries and for
  factual lookups once it has an unambiguous ID to seize on.
- **Vector is the right tool** for semantic/exploratory reasoning,
  exact-match lexical retrieval, and — in practice, on this corpus — for
  relational queries phrased descriptively rather than by literal name,
  because the graph arm's entity recognition doesn't yet bridge that gap.
- **Neither hallucinates** when the corpus genuinely doesn't cover a
  question — refusal-test accuracy is 100% on both arms.

The two remaining open items (the graph arm's literal-only entity
matching, and the "unknown" entity-collapse problem that's real but
currently invisible to this eval's probe) are documented, not hidden, in
`docs/EVAL_RESULTS.md`.
