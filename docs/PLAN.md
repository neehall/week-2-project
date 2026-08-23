# Two Arms, One Corpus — Architecture & Eval Plan

Full interactive version (with the architecture diagram):
https://claude.ai/code/artifact/fde0d0ff-9c4e-44f2-95b2-01472a10dc98

## Architecture

Every query enters through one LangGraph state machine and is answered
twice — once by a hybrid vector retriever, once by graph traversal —
before either arm is allowed to generate:

```
parse_query
    ├── retrieve_vector   (hybrid: dense + BM25 → rerank → top-5 chunks)
    └── retrieve_graph    (entity match → traverse 1-2 hops)
            │
      confidence_gate
       ├── below threshold  → refuse
       └── sufficient evidence → generate cited answer
```

A shared confidence gate — not the LLM — decides whether to answer or
refuse, so weak retrieval never reaches generation.

## Chunk size ↔ embedding capacity

| Embedding model | Dimensions | Recommended chunk size |
|---|---|---|
| all-MiniLM-L6-v2 (local) | 384 | 200-300 tokens |
| text-embedding-3-small (Nebius/OpenAI) | 1536 | 400-600 tokens (default) |
| text-embedding-3-large | 3072 | 600-900 tokens |

Chunk code blocks separately from prose — exact identifiers inside code
(function names, error strings) are what dense retrieval is weakest at,
which is why the vector arm is hybrid, not pure dense.

## Hybrid retrieval

- Dense retrieval: embedding similarity, catches paraphrase/semantic intent
- BM25 (sparse): term-frequency match, catches PR numbers/usernames/error
  codes/function names exactly
- Fusion + rerank: combine both result sets (reciprocal rank fusion), then
  rerank the merged top ~20 with a cross-encoder down to the top 5

## Refusal path (designed first)

The confidence gate checks both arms independently: the vector arm refuses
when the top reranked score falls below threshold; the graph arm refuses
when entity matching finds no corresponding node, or traversal returns an
empty subgraph. If both arms are below threshold, refuse outright.

> "I couldn't find this in the LangChain repo data I've indexed. Try
> rephrasing, or this may be outside what I've ingested."

## The 10-query comparison set

| # | Query type | Example | Expected edge |
|---|---|---|---|
| 1 | Single-hop factual | Who authored PR #4213? | tie |
| 2 | Multi-hop relational | Who reviewed the PR that fixed the memory leak, and what module does it touch? | graph |
| 3 | Aggregation / list | List every contributor to the retrievers module this quarter. | graph |
| 4 | Semantic / exploratory | Why did the team move away from the original conversation buffer design? | vector |
| 5 | Exact-match / lexical | Which PR references error code `ECONNRESET`? | vector (hybrid) |
| 6 | Decision provenance | What was decided about the retriever interface change, and who approved it? | graph |
| 7 | Ambiguous entity | What did Alex work on last month? (multiple contributors named Alex) | stress test |
| 8 | Cross-document synthesis | Summarize the discussion across all issues tagged `streaming`. | tie |
| 9 | Out-of-corpus (refusal test) | Who approved LangChain's pricing model? | must refuse |
| 10 | Plausible but unindexed (refusal test) | What did the team decide about the Rust rewrite? | must refuse |

Queries 9-10 aren't padding: a system that scores well on 1-8 but
hallucinates on 9-10 has a broken refusal path — the more expensive failure
mode.

## Evaluation methodology

| Metric | How it's scored |
|---|---|
| Faithfulness | Does every claim trace to a retrieved chunk/edge? LLM-judge rubric + manual spot-check. |
| Relevance | Does retrieved context actually address the question. |
| Correct refusal rate | On queries 9-10: did the system refuse instead of hallucinating? |
| Latency | Wall-clock time per arm, per query. |

## Build sequence

1. Ingest and clean (GitHub API pull)
2. Build the vector index (chunk, embed, BM25, fuse, rerank)
3. Build the graph (entity/relationship extraction, 20+ nodes)
4. Wire the LangGraph state machine
5. Write and run the 10-query set
6. Score and write up the comparison
7. Package: project doc, demo video, GitHub assets
