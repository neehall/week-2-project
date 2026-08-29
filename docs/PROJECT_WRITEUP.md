# GraphRAG for Organizational Knowledge — Project Write-up

**Project:** Two Arms, One Corpus — hybrid vector-RAG vs. GraphRAG, compared head-to-head
**Repo:** github.com/neehall/week-2-project
**Full investigation log:** `docs/EVAL_RESULTS.md` (bugs found, root causes, every number's provenance — section 2 below is the presentation-oriented summary of that log)

## 1. Project Overview

The project builds two independent retrieval "arms" — a hybrid vector-RAG
pipeline and a GraphRAG pipeline — over the same corpus, and runs both on
every query so the difference between "semantic similarity retrieval" and
"structured relationship traversal" can be measured directly, rather than
picking one architecture and asserting it's better.

**One-liner:** *My RAG app helps open-source contributors and maintainers
answer "who worked on what, and what decisions were made and by whom"
questions from the LangChain GitHub repo's contributors, PRs, issues, and
RFCs, in a simple chat interface, with grounded, cited answers.*

### Architecture

![Architecture diagram](assets/architecture.png)

Both arms run in parallel on every query, wired through a LangGraph state
machine (`app/graph_flow.py`). A shared confidence gate — not the LLM —
decides whether to answer or refuse, so weak retrieval never reaches
generation. The refusal path was designed *before* the happy path, on the
premise that a system that hallucinates when retrieval comes up empty is
worse than one that says it doesn't know.

### Stack

| Component | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | Explicit state machine, parallel fan-out/fan-in for both arms, a real branch (not a prompt instruction) for the confidence gate |
| Vector store | Chroma (local) + `rank_bm25` (sparse) | Hybrid retrieval — dense catches paraphrase/semantic intent, BM25 catches exact identifiers (PR numbers, error codes, usernames) that dense embeddings are weak on |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranks the fused top ~20 candidates down to the top 5 that reach generation |
| Embeddings | `all-MiniLM-L6-v2` (local, sentence-transformers) | No API key required; swapped in from the original Nebius-hosted plan once it became clear no Nebius key was available |
| Graph store | NetworkX (in-memory) | No server required; a Neo4j backend is scaffolded (`GraphStore(backend="neo4j")`) but not implemented — not needed for this project's scale |
| Generation | Claude (`claude-opus-5`) via the official `anthropic` SDK | Swapped in from the original Nebius-hosted LLM plan, same reason as embeddings |
| UI | Streamlit | Minimal chat interface wrapping the compiled LangGraph flow |

## 2. Comparison Results: GraphRAG vs. Vector-RAG Head-to-Head

A focused, presentation-oriented summary of how the two retrieval arms
compare on the same 16 questions (the original 10, plus 6 edge cases added
in a later pass — see "Query set" note below). For the full investigation
log — bugs found, root causes, and how each number was arrived at — see
`docs/EVAL_RESULTS.md`. Raw data: `data/eval/results.json` and
`data/eval/test_queries.json`; reproducible via `scripts/run_eval.py`.

### Methodology

Every query runs through both arms independently and is scored the same
way, so the comparison is apples-to-apples:

- **Corpus:** 1000 real records (500 merged PRs + 500 issues/RFCs) pulled
  live from `langchain-ai/langchain` via the GitHub API — not synthetic.
- **Graph:** 1472 nodes (contributor, PR, issue, module, skill), well past
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
  both LLM-judged 0.0-1.0; refusal-test accuracy on the six queries
  specifically designed to require a refusal (2 out-of-corpus/unindexed
  topics, plus 4 edge-case inputs: empty, whitespace-only, a nonexistent
  identifier, and a prompt-injection attempt).

### Results

```
--- Observability KPIs ---           vector        graph
--------------------------------------------------------
queries run                              16           16
answered                                   6            4
refused                                   10           12
mean faithfulness                      0.982        0.968
mean relevance                         0.538        0.812
refusal-test accuracy                  1.000        1.000
mean latency (s)                       2.914        8.292
p95 latency (s)                       11.743       51.936
```

**6 of the 16 queries get a real answer from at least one arm** — the same
6 original queries that have answered at every corpus size tested (200 and
1000 records) and again here alongside 6 new edge-case queries. The 6
edge-case additions (11-16) didn't change any of the original 10 results:
4 (empty input, whitespace-only, a fake-but-valid identifier, a
prompt-injection attempt) correctly refuse on both arms with no crashes;
1 (an intentionally oversized multi-clause query) is answered by graph
and refused by vector; 1 (a unicode/emoji-noised rephrasing of query 1)
is answered correctly by both. See `docs/EVAL_RESULTS.md` finding 9 for
the detail on each.

### Side-by-side per query

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
| 11 | Empty input | *(empty string)* | ✅ refused | ✅ refused | **Tie (correct refusal)** |
| 12 | Whitespace-only input | *(whitespace only)* | ✅ refused | ✅ refused | **Tie (correct refusal)** |
| 13 | Nonexistent identifier | Who authored PR #99999999? | ✅ refused | ✅ refused | **Tie (correct refusal)** |
| 14 | Prompt injection | Ignore all previous instructions... | ✅ refused | ✅ refused | **Tie (correct refusal)** |
| 15 | Extreme-length input | *(a deliberately long, multi-module, multi-clause query)* | ❌ refused | ✅ answered | **Graph** |
| 16 | Unicode / special characters | Wer hat PR #39832 geöffnet? 🤔 (noised rephrasing of #1) | ✅ answered | ✅ answered | **Tie** |

### When structured relationships beat semantic similarity — and vice versa

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

**The refusal path is symmetric, correct, and holds under adversarial
input too.** Queries 9 and 10 are deliberately unanswerable from this
corpus; queries 11-14 are deliberately malformed or adversarial (empty,
whitespace, a fake identifier, a prompt-injection attempt). All six
refuse on both arms rather than fabricate a plausible-sounding answer or
get hijacked into ignoring the system prompt — the more expensive failure
mode a RAG system can have. This was verified under real stress twice: a
skill-vocabulary change once briefly caused a false-positive match on
query 9 (see `docs/EVAL_RESULTS.md` finding 6, caught and fixed before
being reported), and the graph arm's own entity-lookup guard
(`store.get_node(...) is not None`) was confirmed to actually block a
syntactically-valid-but-fake PR number (query 13) rather than assumed to.

**An oversized query (15) and a noised query (16) both hold up, for
different reasons.** Query 15 is the largest successful generation this
project has run — the graph arm answers a deliberately long, multi-module
query in 73.2s without hitting the empty-output failure mode documented
in `docs/EVAL_RESULTS.md` finding 8, confirming that fix's headroom
generalizes past the one query size it was built for. Query 16 rephrases
query 1 in German with emoji and stray punctuation around the same PR
number — both arms still find and correctly cite it, though vector's
*relevance* score comes back oddly low (0.15) despite full faithfulness
(1.00), a judge-sensitivity quirk noted in finding 9 rather than a
retrieval defect.

### Bottom line

The comparison shows real, query-type-dependent signal rather than one
architecture uniformly beating the other:

- **Graph is the right tool** for aggregation/list queries and for
  factual lookups once it has an unambiguous ID to seize on.
- **Vector is the right tool** for semantic/exploratory reasoning,
  exact-match lexical retrieval, and — in practice, on this corpus — for
  relational queries phrased descriptively rather than by literal name,
  because the graph arm's entity recognition doesn't yet bridge that gap.
- **Neither hallucinates** when the corpus genuinely doesn't cover a
  question, and neither can be talked out of the refusal path by
  malformed or adversarial input — refusal-test accuracy is 100% on both
  arms across all six refusal-test queries.

Three items remain genuinely open — the graph arm's literal-only entity
matching, the "unknown" entity-collapse problem that's real but currently
invisible to this eval's probe, and generation's reliance on a static
token budget for a subgraph size that scales with the corpus (the current
fix is headroom, not a structural cap) — all documented, not hidden, in
`docs/EVAL_RESULTS.md`.

## 3. Dataset Used

**Source:** the public `langchain-ai/langchain` GitHub repository — PRs,
issues, and RFC-style discussions — pulled live via the GitHub REST API
(PyGithub), not a static/synthetic fixture.

**What's kept per record:** title, cleaned body, author, reviewers, linked
issue numbers, merge date, and (for PRs) the dominant module path touched
— the structured metadata the graph is built from, not just the raw text.

**Cleaning:** bot-authored comments/reviews are dropped (`[bot]`-suffixed
usernames normalized to `"unknown"`), HTML comments stripped, and fenced
code blocks are protected from prose-cleaning so identifiers inside code
aren't mangled.

**Size, pulled incrementally:**

| Pull | PRs | Issues/RFCs | Total records | Time | Rationale |
|---|---|---|---|---|---|
| 1 | 20 | 20 | 40 | 123s | Initial dev-scale pull |
| 2 | 50 | 50 | 100 | 123s | First scale-up, checked GitHub rate limit + query-term coverage |
| 3 | 100 | 100 | 200 | 251s | Coverage of eval-query terms plateaued here for anything tied to fabricated specifics, confirming further scaling wouldn't help those |
| 4 | 500 | 500 | 1000 | 428s | A later, separate 5x scale-up to stress-test the pipeline at a larger size — final corpus, committed to the repo |

At the current 1000-record scale, chunking (~250-token chunks, sized for
the 384-dim local embedding model) produces 8105 chunks, and graph
construction produces 1472 nodes (well past the 20-node minimum) across
five node types: contributor, PR, issue, module, and **skill**
(tools/technologies — see the graph schema note below).

**Known limitation, stated explicitly rather than glossed over:** this is
a one-time snapshot of the most-recently-updated slice of a large,
long-lived repository — not a live sync, and not comprehensive. A query
about a real but older or unrelated part of the repo's history will
correctly refuse, not because the system is broken, but because that
content was never ingested.

## 4. Prompts / Agent Instructions Used

### Generation system prompt (`app/core/generation.py`)

```
You answer questions about the langchain-ai/langchain GitHub repo using
only the context provided below — either retrieved text chunks or a
serialized graph subgraph. Every factual claim must carry an inline
citation to its source: [chunk_id] for a vector chunk (e.g.
[pr-4213-0]), or a node id for a graph fact (e.g. [contributor:alice]).
If the context doesn't support an answer, say so explicitly rather
than guessing or using outside knowledge.
```

Design intent: force per-claim citation (not just "here's a source
somewhere in the answer") and explicitly instruct the model to admit a
gap rather than fill it with outside knowledge. This was tested directly
— a query correctly retrieved the right PR but the chunk's text didn't
contain author information, and the model answered "the provided context
doesn't include author information for PR #39832" rather than guessing,
confirming the instruction holds under real retrieval gaps, not just in
the abstract.

### LLM-judge grading prompt (`app/core/evaluation.py`)

Used to score faithfulness (does every claim trace to the retrieved
context?) and relevance (does the retrieved context address the query?)
for the eval harness:

```
You are a strict grader. Respond with exactly one line:
SCORE: <a number between 0.0 and 1.0>. You may add one short
sentence of justification after that line.
```

Paired with a task-specific question appended per call, e.g.: *"Does
every factual claim in the answer trace back to the retrieved context
above? Score 1.0 if every claim is supported by the context... 0.0 if it
states facts not present in the context."*

### Refusal message (`app/common/config.py`)

```
I couldn't find this in the LangChain repo data I've indexed. Try
rephrasing, or this may be outside what I've ingested.
```

## 5. Iterations Tried

The project went through several rounds of build → test-against-real-data
→ find a real bug → fix → re-verify, rather than a single linear build.
The notable iterations:

1. **Ingestion reliability.** An early full ingestion run took 30+
   minutes. Root-caused to two compounding issues: `.env` was never
   actually loaded (`python-dotenv` was a listed dependency but
   `load_dotenv()` was never called anywhere), so the run fell back to
   GitHub's unauthenticated 60 req/hr limit; and the GitHub client had no
   request timeout, so a stalled connection just hung. Fixed both, plus
   added a wall-clock time budget independent of record limits. Verified:
   the same-shaped pull dropped from 30+ minutes to 52 seconds.

2. **Embedding/generation model swap.** The original plan specified a
   Nebius-hosted embedding and generation model. No Nebius API key was
   available. Rather than block, swapped to a local `all-MiniLM-L6-v2`
   embedding model (no key required, chunk size adjusted to match its
   384 dimensions per the plan's own capacity table) and Claude for
   generation (a GitHub-CLI-style credential wasn't available for
   Anthropic, so this required the user to generate and paste an API
   key).

3. **Vector confidence score wasn't 0-1.** The cross-encoder reranker
   returns raw logits (observed as low as -9), not a bounded similarity
   score — but the confidence gate's threshold assumed a 0-1 range.
   Fixed with a sigmoid transform; recalibrated against real in-corpus vs.
   out-of-corpus queries afterward (paraphrased in-corpus queries scored
   ~0.995-0.999, out-of-corpus queries ~0.0003-0.11 at initial testing).

4. **First 10-query eval run: 20/20 refusals.** The original 10-query
   comparison set was written as generic templates (a specific PR number,
   an invented contributor name, a fabricated error code) before any real
   corpus existed. Running it against the real data produced universal
   refusal — not a broken pipeline, but a query set that didn't describe
   anything in the actual corpus. Confirmed via direct term search before
   concluding this (9 of 10 reference terms had zero occurrences).
   Rewrote 7 of the 10 queries to be grounded in real, verified corpus
   content; kept the 2 refusal-test queries and the 1 query that already
   happened to match.

5. **A real scoring bug in the eval harness itself.** The rewritten
   queries' first full run reported mean faithfulness 0.32-0.49 despite
   manual inspection showing well-cited, clearly-grounded answers.
   Root-caused: the LLM-judge call's `max_tokens=200` didn't leave
   headroom for Claude Opus 5's default adaptive thinking, which shares
   the same token budget as the visible answer — intermittently
   truncating the response before it reached the score line and silently
   falling through to a 0.0 default. Confirmed by replaying an identical
   judge call twice and getting a thinking block once, plain text the
   other time. Fixed by raising `max_tokens` and lowering reasoning
   effort for this simple grading task; re-verified against real content
   before trusting the re-run.

6. **A truncation bug found only by actually running the UI.**
   Wiring up the Streamlit chat interface and driving it end-to-end
   (headless Chromium, not just an import check) surfaced a second real
   bug: a graph-arm aggregation answer over a larger subgraph was cut off
   mid-word. `GENERATION_MAX_TOKENS` (1024) was sized for the original
   40-record corpus and was too small once the corpus grew. This bug was
   invisible to every prior check (`refused` and the numeric scores)
   because a truncated-but-non-empty answer doesn't trip any of them —
   it only became visible by reading a real rendered answer.

7. **Deeper investigation of two "known open items."** Two limitations
   were initially written up as "the vector confidence threshold
   probably needs retuning at the larger corpus size" — a plausible but
   imprecise diagnosis. Digging one level deeper (tracing exact chunk
   scores, BM25 ranks, and fused-candidate-pool membership for the
   specific failing queries) found two more precise, different root
   causes instead:
   - A PR/issue's identifying **number was never embedded in the
     chunk's searchable text** — only carried in metadata — so a query
     naming a record by number was architecturally invisible to both
     BM25 and dense retrieval, regardless of any threshold value.
   - A correctly-retrieved, correctly-ranked-#1 passage was still
     under-scored by the cross-encoder because the passage text never
     self-identified as belonging to a PR — a reranker blind spot, not a
     retrieval failure.
   - Threshold retuning alone was checked and found mathematically
     incapable of fixing one of the two cases (the true refusal-test
     query's real score sat *between* the two problem queries' scores,
     meaning no single cutoff could separate all three correctly).
   Fixed by prepending a self-identifying `"PR #1234: title"` header to
   *every* chunk (not just the lead-in segment, which was the original,
   incomplete version of this fix) — re-verified against the exact
   failing queries and re-ran the full 10-query comparison, confirming
   the fix (vector arm went from 3/10 to 5/10 queries answered, with
   faithfulness holding steady, not dropping — 6/10 unique queries get
   an answer from at least one arm, since graph uniquely answers one
   the vector arm doesn't).

8. **A gap against the original project brief, found by re-reading the
   brief against the actual code rather than from memory.** The brief
   models org knowledge as people/projects/**skills**/documents/
   decisions. The graph schema covered four of the five — no "skill"
   node type existed. Rather than invent an arbitrary keyword scan,
   looked for a convention this specific corpus already uses reliably:
   conventional-commit title scopes (`fix(anthropic): ...`) and
   Dependabot-style "bump X from A to B" titles both name real
   tools/technologies. Added a `skill` node type and a `uses` edge
   sourced from those two patterns (the commit-scope source is
   intersected with a curated allowlist so internal module scopes like
   "core" or "infra" aren't misclassified as external tools). No new
   edge type was needed to answer "what tools did a contributor use" —
   that's the same 2-hop traversal pattern already used for
   contributor→module. Verified end-to-end against the brief's own
   example query shape ("what did X work on and what tools did they
   use") — it now answers with a dedicated, fully-cited "Tools / skills
   used" section.

9. **The skill-node fix above introduced its own regression, caught by
   re-running the full comparison rather than trusting the one query it
   was built for.** Adding `"langchain"` to the curated skill vocabulary
   (a genuine conventional-commit scope in this corpus) broke a refusal
   test: "Who approved LangChain's pricing model?" started getting
   *answered* by the graph arm instead of refused, because the product's
   own name in the question false-matched `skill:langchain` — a false
   positive that would trigger on almost any query mentioning the
   product by name, since that's the subject of the entire corpus.
   Root cause: unlike the other 11 tool names (openai, anthropic,
   deepseek, ...), "langchain" isn't a tool distinct from the repo
   itself. Fixed by removing it from the vocabulary; re-verified the
   refusal test passes again and the original tools-traversal query
   still works; re-ran the full 10-query comparison once more to confirm
   no other regression before reporting final numbers.

10. **Scaling the corpus 5x (200 → 1000 records) surfaced two more real
    bugs that simply didn't exist at any smaller size tested.** First:
    the vector store crashed outright —
    `chromadb.errors.InternalError: Batch size of 8105 is greater than
    max batch size of 5461` — because Chroma enforces a hard per-`add()`
    call limit that only 1000 records' worth of chunks (8105) actually
    crossed; every earlier size (up to 1157 chunks at 200 records) was
    comfortably under it. Fixed by batching the insert calls at 2000
    chunks each instead of one call for the whole corpus.

11. **Fixing the batching bug immediately surfaced a second, more subtle
    one: the earlier `GENERATION_MAX_TOKENS` fix (iteration 6) held at
    200 records but broke again, worse, at 1000.** The same query
    ("list every contributor to the agents module") went from "cut off
    mid-word" to **completely empty** — the module now spans 34 PRs
    instead of 6, so its subgraph is ~51K characters / ~24.5K input
    tokens, and Claude Opus 5's adaptive thinking consumed the *entire*
    4096-token output budget as hidden reasoning before writing any
    visible text (`stop_reason: "max_tokens"`, `thinking_tokens: 4096`).
    Same underlying failure mode as the eval-judge bug (iteration 5) —
    thinking sharing the budget with the visible output — now hitting
    real generation because subgraph size scales with corpus size in a
    way a fixed token budget doesn't. Fixed by raising the budget to
    8192 (real headroom, not just enough for the one size tested) and
    capping reasoning effort to `"medium"` so less of the budget goes to
    unbounded thinking. Re-verified against the exact failing query
    (8013 characters, completes naturally) before re-running the full
    comparison — the answered/refused pattern held completely unchanged
    from the 200-record corpus, real evidence the earlier result wasn't
    a corpus-size coincidence.

## 6. Learnings / Observations

- **A system that never gets run end-to-end will hide bugs that only
  exist end-to-end.** Two of the more consequential bugs in this project
  (the `.env`-never-loaded ingestion hang, and the generation truncation
  on a larger corpus) were invisible to unit-level checks and only
  surfaced by actually running the real pipeline against real data — the
  first by watching a wall-clock timer, the second by reading an actual
  rendered UI screenshot rather than trusting a `refused: False` flag.

- **A "confidence score" is often measuring the wrong thing.** The
  cross-encoder's reranked score measures topical relevance between a
  query and a passage — not whether that passage actually contains the
  fact being asked for. A query can retrieve the exactly-right document
  with high confidence and still have no answer inside it (PR title
  present, author absent) — the system's job then is to say so, not to
  either hallucinate or refuse outright. That distinction — evidence
  found vs. evidence sufficient — isn't something a single threshold can
  fully capture.

- **An initial diagnosis of "needs retuning" was too shallow, and saying
  so explicitly was the right call.** The first-pass write-up flagged a
  confidence threshold as needing recalibration. One level deeper, the
  real causes were two specific, structural bugs (a missing identifier in
  indexed text; a reranker blind spot on self-referential-less passages)
  that a threshold change could never have fixed — and the maths showed
  it explicitly (the "right" query for the true refusal test scored
  *between* the two problem queries, so no cutoff could separate all
  three). Retuning the number would have papered over the actual issue.

- **GraphRAG and vector-RAG fail differently, not just "graph wins here,
  vector wins there."** The most interesting eval result wasn't which arm
  won on which query type (though that mostly matched expectations —
  graph on aggregation, vector on semantic/exploratory) — it was the
  cases that *flipped*. Two queries expected to favor the graph arm
  instead got answered by vector, because the graph arm's entity matcher
  requires a query to literally name a PR/username/module rather than
  describe it. That's a specific, fixable gap in entity recognition, not
  a case of "the graph arm is worse."

- **An eval harness needs its own eval.** The LLM-judge scoring bug (item
  5 above) is a reminder that a scoring layer built on the same kind of
  model it's grading can inherit that model's own quirks (here: adaptive
  thinking consuming a token budget meant for the visible answer) in ways
  that produce plausible-looking but wrong numbers. The fix was caught
  only by manually reading real answers and noticing the scores
  contradicted them — automated scores were trusted only after that
  spot-check, not before.

- **Corpus/query-set mismatch is itself worth documenting, not silently
  fixing.** The first full 10-query run produced a 20/20 refusal rate.
  The honest path was to report that result plainly, explain why (a
  query set written before any corpus existed), and only then decide
  how to fix it — rather than quietly rewriting the queries first and
  presenting a "clean" result as if that had always been the plan.

- **Re-checking the original brief against the actual code — not
  against memory of what was planned — found a real gap.** The graph
  schema had quietly drifted to four node types instead of the brief's
  five somewhere between `docs/SCOPE.md`'s early scoping (a reasonable
  domain adaptation) and the final implementation, and it went
  unnoticed through several rounds of testing because every eval query
  happened to route through the four types that existed. A deliberate
  line-by-line check against the brief's literal text — not just "does
  the demo work" — is what surfaced it.

- **"Works at this size" and "works" are different claims, and testing
  at only one scale can't tell them apart.** Two real bugs (a hard
  Chroma batch limit, and a generation token budget that quietly
  depended on subgraph size) existed in code that had already passed
  every check at 40, 100, and 200 records — they were only ever a
  function of corpus size, not correctness at any size tested. The fix
  wasn't "test more at 200 records," it was deliberately scaling 5x and
  re-running the exact same checks, which is what actually found them.
  The payoff of doing that: the query-level answered/refused pattern
  itself held perfectly stable across the scale-up — genuine evidence
  the comparison's conclusions aren't a small-corpus artifact.
