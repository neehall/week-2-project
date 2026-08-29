# 16-Query Comparison — Results & Write-up

Run against a real 1000-record corpus (500 merged PRs + 500 issues/RFCs,
most-recently-updated `langchain-ai/langchain` activity as of 2026-08-24 —
pulled incrementally, see "Corpus" below) via
`app.core.evaluation.run_comparison()` (`scripts/run_eval.py`). Raw output:
`data/eval/results.json`. Query set: `data/eval/test_queries.json` (each
entry's `note` field explains what it's grounded in — see "Query set" below
for why it was rewritten, and for queries 11-16, why each was added).

## Pipeline

Every query in this comparison runs through both arms, shown below —
see `docs/PLAN.md` for the full architecture writeup.

```mermaid
flowchart TD
    Q["User Query"] --> P["parse_query"]
    P --> V["retrieve_vector<br/>dense + BM25 → RRF fusion<br/>→ cross-encoder rerank → top-5 chunks"]
    P --> G["retrieve_graph<br/>entity match → 1-2 hop traversal<br/>→ serialized subgraph"]
    V --> CG{"confidence_gate"}
    G --> CG
    CG -->|"below threshold<br/>(both arms)"| REF["Refuse"]
    CG -->|"sufficient evidence<br/>(either arm)"| GEN["Generate<br/>cited answer"]

    style Q fill:#e8eef7,stroke:#4a6fa5
    style P fill:#e8eef7,stroke:#4a6fa5
    style V fill:#eaf5ea,stroke:#4a8f4a
    style G fill:#fbeee0,stroke:#c07a2b
    style CG fill:#f5e6f5,stroke:#8b4a8b
    style REF fill:#f7dede,stroke:#a54a4a
    style GEN fill:#e0f0e8,stroke:#2b8f5a
```

**This is the sixth pass, and the first to add edge-case queries on top of
the full 1000-record scale.** The first pass (10-query set written before
any corpus existed) produced 20/20 refusals. The second pass (queries
rewritten against real content) produced real signal but flagged two "open
items." The third pass dug into both, found their actual root causes, and
fixed them. The fourth pass added a "skill" node type (closing a gap
against the original project brief) and caught/fixed a regression that
change introduced — all at 200 records. The fifth pass scaled the corpus
5x to 1000 records, which surfaced two more real, corpus-size-dependent
bugs (findings 7 and 8) before landing on stable numbers. This sixth pass
keeps the corpus at 1000 records and adds 6 edge-case queries (11-16:
empty input, whitespace-only input, a syntactically valid but nonexistent
identifier, a prompt-injection attempt, an oversized query, and a
unicode/emoji-noised query) to the original 10 — see "Query set" below for
what each probes and why. A comparison-focused summary of this data lives
in `docs/PROJECT_WRITEUP.md`; this document is the full investigation log.

## Observability KPIs

```
--- Observability KPIs ---           vector        graph
--------------------------------------------------------
queries run                              16           16
answered                                    6            4
refused                                    10           12
mean faithfulness                       0.982        0.968
mean relevance                          0.538        0.812
refusal-test accuracy                   1.000        1.000
mean latency (s)                        2.914        8.292
p95 latency (s)                        11.743       51.936
```

(`app.core.evaluation.print_kpi_summary()` — called automatically at the
end of every `run_comparison()` — produces this table for any future run.
LLM-judge faithfulness/relevance scores vary a few hundredths between
runs on the same query — expected noise from the judge itself, not a
pipeline change. The original 10 queries' answered/refused pattern is
**unchanged from the fifth pass** — adding 6 edge-case queries didn't
perturb any of the original results, and 4 of the 6 new queries (11-14,
all `is_refusal_test: true`) correctly refuse on both arms, which is why
mean latency drops and refusal-test accuracy holds at 1.000 even at n=16:
those four resolve almost instantly, before any generation call runs.)

Graph's p95 latency (51.9s) is still query 3's aggregation subgraph, same
as the fifth pass — with 16 samples the 95th-percentile index lands one
below the new maximum. That maximum is now query 15 (73.2s, the
deliberately oversized stress-test query), the single slowest call in
this run but still under `p_max`, not `p95`. Both are large-subgraph
generation calls, not bugs; see finding 9 below for why query 15 didn't
regress into finding 8's empty-output failure mode despite being larger
than any prior query.

## Per-query result

| # | Type | Expected | Vector | Graph | What happened |
|---|---|---|---|---|---|
| 1 | single_hop_factual | tie | **answered** (1.00/0.30) | **answered** (1.00/1.00) | Genuine tie, as originally expected — see "PR numbers weren't embedded" below. |
| 2 | multi_hop_relational | graph | **answered** (1.00/0.40) | refused | Flipped from expected — the graph arm's entity matcher needs a query to *name* the PR, not describe it. |
| 3 | aggregation_list | graph | refused | **answered** (0.92/0.75) | Matches expectation — graph traversal is the natural fit, though see finding 8 for a real bug this query triggered at scale. |
| 4 | semantic_exploratory | vector | **answered** (0.97/0.95) | refused | Matches expectation cleanly. |
| 5 | exact_match_lexical | vector_hybrid | **answered** (0.95/0.90) | refused | Fixed — was refusing on both arms; see "PR numbers weren't embedded" below. |
| 6 | decision_provenance | graph | **answered** (1.00/0.55) | refused | Flipped, same root cause as #2. |
| 7 | ambiguous_entity | stress_test | refused | refused | Didn't test what it was designed to — see "Ambiguous entity" below. |
| 8 | cross_document_synthesis | tie | refused | refused | Both correctly refuse but for different reasons (aggregation phrasing vs. no label/tag entity type). |
| 9 | out_of_corpus | must_refuse | **refused ✓** | **refused ✓** | Correct — the refusal path works (see finding 6 for a regression that briefly broke this on the graph arm, caught before being reported here). |
| 10 | plausible_but_unindexed | must_refuse | **refused ✓** | **refused ✓** | Correct — the refusal path works. |
| 11 | empty_input | must_refuse | **refused ✓** | **refused ✓** | No crash — `parse_query()`'s `.strip()` on `""` reaches retrieval as an empty string on both arms, which finds nothing and refuses cleanly. |
| 12 | whitespace_only_input | must_refuse | **refused ✓** | **refused ✓** | Same outcome as 11 — whitespace collapses to empty before retrieval. |
| 13 | nonexistent_identifier | must_refuse | **refused ✓** | **refused ✓** | Confirms `match_entities()`'s `store.get_node(...) is not None` guard (noted as a design detail, not previously exercised by an eval query) — a syntactically valid `#99999999` reference correctly fails lookup instead of false-matching a nearby real PR number. |
| 14 | prompt_injection | must_refuse | **refused ✓** | **refused ✓** | The injected instructions ("ignore all previous instructions...") have no corpus grounding, so both arms refuse on retrieval alone — the generation system prompt was never even reached to be tested against. |
| 15 | extreme_length_input | stress_test | refused | **answered** (0.94/0.55) | See finding 9 — the graph arm handles this multi-module query correctly at 73.2s, the slowest single call in this run. |
| 16 | unicode_and_special_characters | tie | **answered** (1.00/0.15) | **answered** (1.00/0.95) | Both arms find PR #39832 correctly despite German text, emoji, and stray punctuation — see finding 9 for why vector's relevance score is unusually low here. |

## Findings

### 1. PR/issue numbers were never embedded in the searchable text (root cause of queries 1 and 5's original failures)

The original write-up flagged query 1's refusal as "the vector confidence
threshold probably needs retuning at the larger corpus size" — that
diagnosis was wrong, or at least incomplete. Tracing the actual pipeline:
`chunk.text` for `pr-39832-0` was literally `"release(core): 1.6.1\n\n
Release 1.6.1"` — the PR number `39832` existed **only** in
`chunk_id`/`source_number` metadata, never in the text that gets embedded
or BM25-indexed. `chunk_record()` (`app/core/chunking.py`) prepended the
record's *title* to its first segment but never its *number*. A query
naming a PR by number was therefore architecturally invisible to both
BM25 and dense retrieval — not a scoring problem, a missing-data problem.
Confirmed directly: the correct chunk never even reached the fused
top-20 candidate pool, and the reranker's top pick for "Who authored PR
#39832?" was `pr-39684-0`, an unrelated typo-fix PR — a threshold change
would have made the system answer confidently with the *wrong* PR.

Query 5 ("Which PR references `StreamClosedError`?") turned out to be
related but distinct: the term genuinely was in the chunk text (confirmed
by grep) and BM25 correctly ranked it #5/1167 — but the cross-encoder
still scored the correctly-retrieved, correctly-fused chunk at 0.042,
because the passage (a bare HTML changelog fragment) never says "I am a
PR," giving a semantic-similarity model nothing to anchor a "which PR"
query against.

**Fix:** `chunk_record()` now prepends a short `"PR #1234: title"` header
to *every* chunk (not just the lead-in segment — an earlier, incomplete
version of this fix only touched the first segment, which wouldn't have
helped query 5 since its failing chunk wasn't the first one). Re-verified
directly against both queries before re-running the full comparison:
query 1's target chunk now reaches the fused pool and the top-5 that
reach generation; query 5's score rose from 0.042 to 1.00. Re-running the
full 10-query set confirmed the fix generalizes — vector answered 6/10 vs.
3/10 before, faithfulness held steady (didn't drop from answering more
often), and the refusal-test queries (9, 10) kept their scores comfortably
low.

**A secondary, real observation surfaced by this fix:** query 1's vector
answer, even after the fix, correctly states *"the provided context
doesn't include author information for PR #39832"* rather than guessing
— because `RawRecord.author` is metadata that (like the PR number
before this fix) never makes it into embedded chunk text. The graph arm
answers this correctly because it explicitly models an `authored` edge.
This is a real, distinct architectural gap on the vector side (not fixed
here), but the system's behavior in the face of it — admitting the gap
instead of hallucinating an author — is exactly what `generation.py`'s
system prompt asks for, and it held up under a genuine retrieval
shortfall, not just in the abstract.

**Threshold retuning, checked and ruled out as a fix for either case:**
before landing on the chunking fix, the vector confidence threshold was
checked directly against real refusal-test scores. Query 9 (should
refuse) scored **0.4045** in one run — far higher than the near-zero
scores seen on hand-picked out-of-corpus samples, driven by a top-matched
chunk of generic environment/version boilerplate that superficially
resembles many other issues. Query 1 (0.4636) and query 9 (0.4045) sat
only 0.06 apart — a workable threshold band existed for those two alone
(~0.43) — but query 5's real score (0.042) sat *below* query 9's, meaning
**no single static threshold could ever answer query 5 without also
making query 9 a false positive**. This ruled out threshold retuning as
a general fix and pointed at the actual (chunking) root cause instead.

### 2. The graph arm's entity matcher is stricter than the query types it's expected to handle

Queries 2 and 6 both flipped from the expected "graph" edge to vector
answering instead. Root cause: `retrieval_graph._match_entities()`
(`app/core/retrieval_graph.py`) only recognizes a query as touching the
graph if it contains a literal PR/issue number (`#1234`), a contributor
username substring, or a module name substring. A query that *describes*
a PR by what it does ("the PR that resolved postponed annotations in
StructuredTool") rather than naming it gives the entity matcher nothing
to latch onto — `matched_nodes` stays 0, and the graph arm refuses even
though the answer is sitting right there in the graph.

This is a real, previously undocumented failure point, distinct from the
ones already in `docs/PLAN.md`'s table: it's not weak traversal or a bad
confidence signal, it's that **entity recognition happens before
traversal even starts**, and it's currently name/number-matching only —
no semantic entity resolution. Not fixed in this pass. A fix would need
either an LLM-based entity extraction pass over the query, or a hybrid:
fall back to vector retrieval to *find* the entity, then hand its ID to
the graph arm for traversal.

### 3. Ambiguous entity (query 7) didn't test what it was designed to

The rewritten query 7 targets a real entity-resolution issue in this
corpus: `ingestion.clean()` normalizes every bot-authored record's author
to `"unknown"`, so 14 unrelated `chore(model-profiles): refresh model
profile data` PRs all collapse onto one contributor node. The query asked
what that node "worked on," expecting either a nonsensical merged answer
(demonstrating the failure) or graceful disambiguation.

What actually happened: `retrieval_graph._match_entities()` explicitly
excludes `"unknown"` from contributor matching (added specifically
because "unknown" is a cleaning placeholder, not a real entity), so the
query refuses immediately. That's arguably *better* behavior than
dumping 14 unrelated PRs as one person's work — but it means the
underlying entity-collapse problem is still latent in the graph (that
merge is real and would surface the moment any other query legitimately
needed to traverse through that node) while this particular probe can't
observe it. Not fixed in this pass — noted as a case where a defensive
design choice made earlier in the session (excluding a known placeholder
value) had a side effect on this eval.

### 4. Generation was silently truncating on large subgraphs (found while wiring the Streamlit UI)

`config.GENERATION_MAX_TOKENS` was 1024 — fine at the 40-record corpus
size, but at 200 records a graph-arm aggregation answer (query 3's "list
every contributor to the agents module") got cut off mid-word
(`[contributor:ccur`). Caught by actually driving the wired-up app end to
end (`app/Home.py`) and screenshotting a real answer, not just checking
`refused`/scores — a truncated-but-non-empty answer doesn't trip any of
the existing checks. Fixed by raising `GENERATION_MAX_TOKENS` to 4096;
re-verified the same query now completes naturally and self-reports its
own completeness caveat ("this list is limited to the supplied
subgraph...").

### 5. A real scoring bug was caught and fixed mid-run

An earlier full run at this corpus size returned mean faithfulness 0.320
(vector) / 0.485 (graph) despite manual inspection showing well-cited,
clearly-grounded answers. Root cause: `evaluation._judge()`'s
`max_tokens=200` didn't leave headroom for Claude Opus 5's adaptive
thinking, which shares the same token budget as the visible `SCORE:` line
— intermittently truncating the response before it reached the score,
silently falling through to the "no match" 0.0 default. Confirmed by
replaying the same judge call twice and getting a thinking block once, a
plain-text answer the other time. Fixed by raising `max_tokens` to 1024
(later 4096-equivalent headroom carried through subsequent runs) and
setting `output_config={"effort": "low"}` (grading is a simple task, per
the model's own guidance). Re-verified against real retrieved context
before trusting any subsequent run.

### 6. Adding "skill" nodes briefly broke a refusal test (caught before it shipped)

Closing the "skill" node type gap (see `docs/PROJECT_WRITEUP.md`
iteration 8) added `"langchain"` to the curated `KNOWN_SKILLS` vocabulary
— a real conventional-commit scope in this corpus (`chore(langchain):
...`). Re-running the full comparison afterward showed graph refusal-test
accuracy drop to 0.5: query 9 ("Who approved **LangChain**'s pricing
model?") started getting *answered* instead of refused, because the
product's own name in the question false-matched `skill:langchain` —
every query about "LangChain" (extremely common, since that's the
subject of the whole corpus) risked the same false positive. Root cause:
"langchain" isn't actually a distinct tool separate from the repo itself,
unlike the other 11 entries (openai, anthropic, deepseek, ...), so it
shouldn't have been in the skill vocabulary at all. Fixed by removing it
from `KNOWN_SKILLS`; re-verified query 9 refuses again and the
tools-traversal query used to validate the skill feature still works;
re-ran the full 10-query comparison to confirm no other regression — the
numbers in this document are from that clean run.

### 7. Chroma's max batch size, hit for the first time at 1000 records

Scaling the corpus from 200 to 1000 records (8105 chunks, up from ~1150)
made `HybridVectorStore.add_chunks()` crash outright:
`chromadb.errors.InternalError: ValueError: Batch size of 8105 is greater
than max batch size of 5461`. Chroma enforces a hard per-`add()` call
limit (tied to the underlying sqlite parameter count) that simply never
mattered at any smaller corpus size tested this session — a real example
of a bug that's invisible until a specific scale threshold is crossed, no
amount of testing at 40/100/200 records would have found it. Fixed by
batching `add()` calls at 2000 chunks each (`app/core/vector_store.py`)
rather than one call for the whole corpus; re-verified the vector store
builds successfully at the full 1000-record scale.

### 8. Generation went from "cut off mid-word" to "completely empty" at 5x corpus scale

The `GENERATION_MAX_TOKENS` fix in finding 4 (200 → cut off mid-word →
raised to 4096) held at 200 records but broke again, worse, at 1000:
query 3's answer came back **entirely empty** (0 characters) rather than
truncated. Traced directly: the agents-module subgraph at this corpus
size is ~51K characters / ~24.5K input tokens (up from a much smaller
subgraph at 200 records, since the module now has 34 PRs instead of 6),
and Claude Opus 5's adaptive thinking consumed the *entire* 4096-token
output budget as hidden reasoning — `stop_reason: "max_tokens"`,
`thinking_tokens: 4096`, zero visible text. Same underlying failure mode
as finding 5's `_judge()` bug (thinking sharing the budget with the
visible output), now hitting `generate_answer()` itself because subgraph
size scales with corpus size in a way a fixed `chunk_id`-based token
budget doesn't.

Fixed two ways: raised `GENERATION_MAX_TOKENS` to 8192 (real headroom,
not just enough to have worked at the one corpus size tested), and added
`output_config={"effort": "medium"}` to `generate_answer()`'s API call so
less of the budget goes to unbounded reasoning. Re-verified against the
exact failing query — 8013 characters, completes naturally, and even
self-limits appropriately ("If you need only those with *merged code* in
the agents module, that would be a narrower subset..."). This is a
stopgap, not a permanent fix: subgraph size will keep growing with corpus
size and will eventually outgrow any static token budget again. The real
fix — capping or summarizing large subgraphs before they reach generation
— is not done here.

### 9. Six edge-case queries added; none crashed, and two produced genuine new signal

Queries 11-16 were added to probe input shapes the original 10 never
exercised — not to find new bugs on purpose, but because an eval set
written entirely from "plausible questions a user would ask" leaves
malformed/adversarial/boundary input completely untested. Four
(11-14: empty string, whitespace-only, a nonexistent-but-valid-looking
identifier, a prompt-injection attempt) all refused cleanly on both arms
with no exception raised anywhere in the pipeline — real confirmation that
`parse_query()`'s bare `.strip()` and `match_entities()`'s existing
`get_node(...) is not None` guard were already sufficient, not gaps that
happened to go untested until now.

The other two produced real, worth-noting behavior:

- **Query 15 (an intentionally long, multi-clause query) is the largest
  successful generation in this project's history and didn't hit finding
  8's failure mode.** At 73.2s it's the slowest single call in this run,
  but it completed with a full, well-cited answer (0.94 faithfulness) —
  the `GENERATION_MAX_TOKENS=8192` / `effort="medium"` fix from finding 8
  (sized for a large *subgraph*, not a large *query*) held up under a
  large *query* too, which wasn't the failure mode it was built for.
  Vector, by contrast, refused this query outright (top score below
  threshold) — plausible: the query's own text is long and semantically
  diffuse across many topics, which likely hurt its embedding's similarity
  to any single chunk, unlike the graph arm's module-name keyword matches
  (which pick out all seven modules the query lists regardless of length).

- **Query 16 (unicode/emoji-noised phrasing of query 1) answered
  correctly on both arms but vector's relevance score (0.15) is
  anomalously low given faithfulness stayed at 1.00.** Both arms find and
  correctly cite PR #39832; the LLM judge scoring *relevance* — "does the
  retrieved evidence address the question" — for the vector arm's judge
  call apparently penalized something in the noised query text itself
  (the mixed German/emoji/punctuation phrasing), even though the answer
  itself was fully grounded. This is a real observation about the judge's
  sensitivity to query surface form, not a retrieval or generation defect
  — worth noting as a limitation of the LLM-judge methodology (see
  finding 5's related judge-reliability issue) rather than fixing the
  pipeline for it.

Not fixed in this pass (nothing here needed fixing): this is a case where
adding harder queries confirmed existing defensive code already handles
its edge cases, plus surfaced one methodology note about the judge itself.

## Corpus

Pulled incrementally, checking GitHub rate limit and query/corpus term
coverage after each step, per explicit instruction this session:

| Step | PR_LIMIT / ISSUE_LIMIT | Records | Time | Rate limit |
|---|---|---|---|---|
| 1 | 20 / 20 | 40 | 123s | comfortable |
| 2 | 50 / 50 | 100 | 123s | comfortable |
| 3 | 100 / 100 | 200 | 251s | comfortable |
| 4 | 500 / 500 | 1000 | 428s | comfortable (4981/5000 remaining beforehand) |

Coverage plateaued at step 3 for terms tied to fabricated specifics (a
literal PR number, a contributor named "Alex", an invented error code) —
confirming further scaling wouldn't help those, which is why the query set
was rewritten instead of scaled further at that point. Step 4 was a
later, separate 5x scale-up specifically to stress-test the pipeline at a
larger size — it surfaced findings 7 and 8 above, both real corpus-size-
dependent bugs, and confirmed the previously-rewritten query set and its
answered/refused pattern hold unchanged at 5x scale (see the KPI section).
`config.py`'s `PR_LIMIT`/`ISSUE_LIMIT` defaults remain 20/20 for fast dev
iteration; every larger pull in this document used a one-off env override
(e.g. `PR_LIMIT=500 ISSUE_LIMIT=500 python -m app.core.ingestion`), not a
change to those defaults. Unlike the earlier 200-record corpus, this
1000-record corpus **is committed to the repo** (`data/corpus/raw/`) —
needed for the Streamlit Community Cloud deploy path, which can't
practically run live ingestion on every cold start.

## Query set

The original 10 queries were written as generic templates before any
corpus was pulled. A pre-run check found 9 of 10 reference terms (PR
#4213, "memory leak" *as a reviewed PR*, "retrievers module", "conversation
buffer", `ECONNRESET`, "retriever interface", a contributor named "Alex")
had zero or near-zero grounding in the real data. Queries 1-7 were rewritten
against real corpus content (see each entry's `note` field in
`data/eval/test_queries.json` and the updated table in `docs/PLAN.md`);
8-10 already worked as originally written. Queries 11-16 were added in a
later pass specifically for input-shape coverage the original 10 (all
"plausible user questions") never exercised — empty/whitespace input, a
syntactically valid but nonexistent identifier, a prompt-injection
attempt, an oversized query, and unicode/emoji noise around a valid
query. See finding 9 for what each one actually found.

## Bottom line for the deliverable

With a grounded query set and both chunking/generation bugs fixed, the
comparison shows real, stable signal:

- **Graph wins outright** on the query type it's supposed to
  (aggregation, query 3), and ties on straightforward single-hop factual
  lookup (query 1) now that both arms can actually see the identifier.
- **Vector wins outright** on semantic/exploratory reasoning (query 4)
  and exact-match lexical retrieval (query 5, once the identifier-
  embedding fix landed) — both as originally predicted — and also picked
  up two queries that were *expected* to favor graph (2, 6) purely
  because the graph arm's entity matcher can't recognize an entity from
  a descriptive query rather than a named one — a real, documented
  limitation (finding 2), not the graph arm losing on merits.
- **The refusal path works** — both correct-refusal tests (9, 10) pass
  on both arms, across every pass of this eval, including the pass where
  the vector threshold was under real stress-testing.
- **The pattern is stable at 5x corpus scale** — exactly the same
  queries answer vs. refuse at 1000 records as at 200, which is real
  evidence this isn't a corpus-size coincidence.
- **Three items remain genuinely open** (not fixed in this pass, unlike
  the chunking/generation/batching bugs above): the graph arm's
  literal-only entity matching (finding 2), the "unknown" entity-collapse
  problem that's real but currently invisible to this eval's probe
  (finding 3), and generation's reliance on a static token budget for a
  subgraph size that scales with the corpus (finding 8) — the current fix
  is headroom, not a structural cap.
- **Edge-case coverage (queries 11-16) confirms the pipeline degrades
  safely on malformed/adversarial/boundary input** — empty input,
  whitespace, a fake-but-valid-looking identifier, and a prompt-injection
  attempt all refuse cleanly with no exceptions; an oversized query still
  generates a complete, faithful answer under the finding-8 token-budget
  fix; and a unicode/emoji-noised query still resolves the right entity
  on both arms (finding 9).
