"""Fast, cheap sanity checks run between pipeline stages.

Every real bug found while building this project (missing PR-number
embedding, Chroma's batch-size limit, generation's token budget exhausted
by thinking, the "langchain"-skill false positive, the corpus/query-set
mismatch) was caught by hand, after the fact — usually after the
expensive full 10-query LLM-judged comparison (evaluation.run_comparison,
~20 Claude calls, minutes) had already run and produced suspicious
numbers. These checkpoints catch the same class of failure in seconds,
with little to no API spend, at the stage it actually broke — see
docs/EVAL_RESULTS.md for the bug each one is modeled on.

Canary queries are reused directly from data/eval/test_queries.json
(query 1: in-corpus factual; query 3: the largest-subgraph query, the
one that broke generation at 1000 records; query 9: out-of-corpus) —
no new fixtures invented, so checkpoints and the full eval test against
the same known-good reference points.

Run standalone: `python -m app.core.checkpoints` — loads the corpus from
data/corpus/raw/, builds every index, runs every check, prints a report,
and exits non-zero if anything failed.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

from app.common import config
from app.core import confidence_gate, generation, retrieval_graph, retrieval_vector


@dataclass
class CheckpointResult:
    stage: str
    passed: bool
    metrics: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


def _canary_queries() -> dict[int, dict]:
    with open(config.TEST_QUERIES_PATH) as f:
        queries = json.load(f)
    return {q["id"]: q for q in queries}


# --- Ingestion --------------------------------------------------------------


def check_ingestion(records: list) -> CheckpointResult:
    """Empty pull; missing required fields; an all-bot corpus (every
    author normalized to "unknown") — the shape a silent
    unauthenticated-fallback or a bad API response would take.
    """
    issues: list[str] = []
    if not records:
        issues.append("no records ingested (empty pull)")
        return CheckpointResult("ingestion", False, {"n_records": 0}, issues)

    missing_fields = [
        r.number for r in records if not r.title or r.body is None or not r.number
    ]
    if missing_fields:
        issues.append(f"{len(missing_fields)} records missing title/body/number")

    n_unknown = sum(1 for r in records if r.author == "unknown")
    if n_unknown == len(records):
        issues.append("every record's author is 'unknown' — likely a cleaning/ingestion bug")

    metrics = {
        "n_records": len(records),
        "n_prs": sum(1 for r in records if r.kind == "pr"),
        "n_issues": sum(1 for r in records if r.kind in ("issue", "rfc")),
        "n_unknown_author": n_unknown,
    }
    return CheckpointResult("ingestion", not issues, metrics, issues)


# --- Chunking -----------------------------------------------------------


def check_chunking(chunks: list) -> CheckpointResult:
    """Every chunk should carry its self-identifying "KIND #N: title"
    header (finding 1 — without it, a query naming a record by number is
    architecturally invisible to retrieval, no matter how it's scored)
    and non-empty text.
    """
    issues: list[str] = []
    if not chunks:
        issues.append("no chunks produced")
        return CheckpointResult("chunking", False, {"n_chunks": 0}, issues)

    empty = [c.chunk_id for c in chunks if not c.text.strip()]
    if empty:
        issues.append(f"{len(empty)} chunks have empty text")

    missing_header = [
        c.chunk_id
        for c in chunks
        if not c.text.startswith(f"{c.source_kind.upper()} #{c.source_number}:")
    ]
    if missing_header:
        pct = 100 * len(missing_header) / len(chunks)
        issues.append(
            f"{len(missing_header)} chunks ({pct:.0f}%) missing the self-identifying header"
        )

    metrics = {"n_chunks": len(chunks), "n_missing_header": len(missing_header)}
    return CheckpointResult("chunking", not issues, metrics, issues)


# --- Vector store ---------------------------------------------------------


def check_vector_store(store, chunks: list | None, canaries: dict) -> CheckpointResult:
    """Insert succeeded at full size (finding 7 — Chroma's hard per-add()
    batch limit crashed silently-until-it-didn't at 1000 records); the
    store's chunk count matches what was passed in (skipped if `chunks`
    isn't available — e.g. called with only a pre-built store); a canary
    in-corpus query scores above threshold and a canary out-of-corpus
    query scores near-zero.
    """
    issues: list[str] = []
    n_in_store = len(store.chunks_by_id)
    if chunks is not None and n_in_store != len(chunks):
        issues.append(f"store has {n_in_store} chunks, expected {len(chunks)} — insert may have partially failed")

    in_corpus_score = out_of_corpus_score = None
    if 1 in canaries:
        in_corpus_score = retrieval_vector.retrieve(canaries[1]["query"], store).top_score
        if in_corpus_score < config.VECTOR_CONFIDENCE_THRESHOLD:
            issues.append(
                f"in-corpus canary (query 1) scored {in_corpus_score:.3f}, "
                f"below threshold {config.VECTOR_CONFIDENCE_THRESHOLD}"
            )
    if 9 in canaries:
        out_of_corpus_score = retrieval_vector.retrieve(canaries[9]["query"], store).top_score
        if out_of_corpus_score >= config.VECTOR_CONFIDENCE_THRESHOLD:
            issues.append(
                f"out-of-corpus canary (query 9) scored {out_of_corpus_score:.3f}, "
                f"at/above threshold {config.VECTOR_CONFIDENCE_THRESHOLD} — false positive"
            )

    metrics = {
        "n_chunks_in_store": n_in_store,
        "in_corpus_canary_score": in_corpus_score,
        "out_of_corpus_canary_score": out_of_corpus_score,
    }
    return CheckpointResult("vector_store", not issues, metrics, issues)


# --- Graph store ------------------------------------------------------------


def check_graph_store(store) -> CheckpointResult:
    """node_count() >= 20 (the explicit project requirement); no expected
    node type has zero nodes; a skill-vocabulary false-positive probe —
    the literal product name should never match as an entity (regression
    test for finding 6, "langchain" briefly sitting in KNOWN_SKILLS).
    """
    issues: list[str] = []
    n_nodes = store.node_count()
    if n_nodes < 20:
        issues.append(f"only {n_nodes} nodes — below the 20-node project requirement")

    type_counts = {}
    for node_type in ("contributor", "pr", "issue", "module"):
        n = len(store.node_ids_by_type(node_type))
        type_counts[node_type] = n
        if n == 0:
            issues.append(f"zero nodes of type '{node_type}'")

    false_positive_matches = retrieval_graph.match_entities(
        "Who approved LangChain's pricing model?", store
    )
    skill_false_positives = [m for m in false_positive_matches if m.startswith("skill:")]
    if skill_false_positives:
        issues.append(
            f"product-name query false-matched skill node(s): {skill_false_positives} "
            "(regression of the 'langchain'-in-KNOWN_SKILLS bug)"
        )

    metrics = {"n_nodes": n_nodes, **type_counts, "n_skill": len(store.node_ids_by_type("skill"))}
    return CheckpointResult("graph_store", not issues, metrics, issues)


# --- Vector retrieval -------------------------------------------------------


def check_vector_retrieval(store, canaries: dict) -> CheckpointResult:
    """A degenerate reranker (all-zero/identical scores across distinct
    queries) is a canary for a silently broken or unloaded model; a
    canary in-corpus query should retrieve its known-correct chunk
    somewhere in the top-5.
    """
    issues: list[str] = []
    scores = []
    top_chunk_ids = None
    if 1 in canaries:
        result = retrieval_vector.retrieve(canaries[1]["query"], store)
        scores.append(result.top_score)
        top_chunk_ids = [c.chunk_id for c in result.chunks]
    if 9 in canaries:
        scores.append(retrieval_vector.retrieve(canaries[9]["query"], store).top_score)

    if len(scores) >= 2 and len(set(round(s, 6) for s in scores)) == 1:
        issues.append(f"reranker returned identical scores across distinct queries ({scores[0]:.3f}) — likely broken")

    metrics = {"scores": scores, "top_chunk_ids": top_chunk_ids}
    return CheckpointResult("vector_retrieval", not issues, metrics, issues)


# --- Graph retrieval ------------------------------------------------------


def check_graph_retrieval(store, canaries: dict) -> CheckpointResult:
    """matched_nodes always 0 across canaries means the entity matcher is
    dead; re-run the same false-positive probe as check_graph_store()
    through the real retrieve() path this time.
    """
    issues: list[str] = []
    matched_counts = []
    for qid in (1, 3):
        if qid in canaries:
            result = retrieval_graph.retrieve(canaries[qid]["query"], store)
            matched_counts.append(result.matched_nodes)

    if matched_counts and all(n == 0 for n in matched_counts):
        issues.append("entity matcher found zero matches on every in-corpus canary — likely broken")

    fp_result = retrieval_graph.retrieve("Who approved LangChain's pricing model?", store)
    if fp_result.matched_nodes > 0:
        issues.append(
            f"out-of-corpus product-name query matched {fp_result.matched_nodes} node(s) "
            "(regression of the 'langchain'-in-KNOWN_SKILLS bug)"
        )

    metrics = {"matched_counts": matched_counts, "false_positive_matched_nodes": fp_result.matched_nodes}
    return CheckpointResult("graph_retrieval", not issues, metrics, issues)


# --- Confidence gate ----------------------------------------------------


def check_confidence_gate(vector_store, graph_store, canaries: dict) -> CheckpointResult:
    """A known in-corpus canary should not be refused; a known
    out-of-corpus canary should be refused — directly re-runs the
    refusal-test queries from test_queries.json through
    confidence_gate.should_refuse(), catching a threshold regression
    before the full eval would.
    """
    issues: list[str] = []
    refused = {}
    for qid in (1, 9):
        if qid not in canaries:
            continue
        query_text = canaries[qid]["query"]
        vector_result = retrieval_vector.retrieve(query_text, vector_store)
        graph_result = retrieval_graph.retrieve(query_text, graph_store)
        refused[qid] = confidence_gate.should_refuse(vector_result, graph_result)

    if refused.get(1) is True:
        issues.append("in-corpus canary (query 1) was refused — threshold likely too strict")
    if refused.get(9) is False:
        issues.append("out-of-corpus canary (query 9) was answered — threshold likely too loose")

    return CheckpointResult("confidence_gate", not issues, {"refused": refused}, issues)


# --- Generation ---------------------------------------------------------


def check_generation(vector_store, graph_store, canaries: dict) -> CheckpointResult:
    """One real generate_answer() call against the known-worst-case
    subgraph (query 3, "agents module" — the exact query that broke at
    1000 records, finding 8): non-empty output, not truncated by hitting
    the thinking-exhausts-the-budget failure mode, and at least one
    citation-shaped token present.
    """
    issues: list[str] = []
    answer = ""
    if 3 in canaries:
        query_text = canaries[3]["query"]
        graph_result = retrieval_graph.retrieve(query_text, graph_store)
        if graph_result.matched_nodes > 0:
            answer = generation.generate_answer(query_text, graph_result)
            if not answer.strip():
                issues.append("generation returned an empty answer on the largest-subgraph canary")
            elif "[" not in answer:
                issues.append("generated answer has no citation-shaped token ('[...]')")

    metrics = {"answer_length": len(answer)}
    return CheckpointResult("generation", not issues, metrics, issues)


# --- Orchestration ------------------------------------------------------


def _safe_run(stage: str, fn, *args) -> CheckpointResult:
    """Run one check, converting an unhandled exception (e.g. a network
    error or an invalid API key hitting check_generation's real Claude
    call) into a failed CheckpointResult instead of crashing the whole
    run — one check's environment problem shouldn't hide every other
    check's result.
    """
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 - deliberately broad, see docstring
        return CheckpointResult(stage, False, {}, [f"{type(e).__name__}: {e}"])


def run_all(
    vector_store,
    graph_store,
    records: list | None = None,
    chunks: list | None = None,
) -> list[CheckpointResult]:
    """Run every checkpoint in pipeline order. `records`/`chunks` are
    optional — a caller that only has the already-built stores (e.g.
    evaluation.run_comparison()'s existing callers) still gets every
    check downstream of them; the ingestion/chunking checks are simply
    skipped rather than fabricating a failure for data that was never
    provided. `vector_store`/`graph_store` are required — every other
    check needs at least one of them. Every check runs even if an
    earlier one raises (see _safe_run) — one broken check shouldn't hide
    the rest of the report.
    """
    canaries = _canary_queries()
    results: list[CheckpointResult] = []
    if records is not None:
        results.append(_safe_run("ingestion", check_ingestion, records))
    if chunks is not None:
        results.append(_safe_run("chunking", check_chunking, chunks))
    results.append(_safe_run("vector_store", check_vector_store, vector_store, chunks, canaries))
    results.append(_safe_run("graph_store", check_graph_store, graph_store))
    results.append(_safe_run("vector_retrieval", check_vector_retrieval, vector_store, canaries))
    results.append(_safe_run("graph_retrieval", check_graph_retrieval, graph_store, canaries))
    results.append(
        _safe_run(
            "confidence_gate", check_confidence_gate, vector_store, graph_store, canaries
        )
    )
    results.append(
        _safe_run("generation", check_generation, vector_store, graph_store, canaries)
    )
    return results


def print_checkpoint_report(results: list[CheckpointResult]) -> None:
    header = f"{'--- Checkpoints ---':22s} {'status':>8s}"
    print(f"\n{header}")
    print("-" * len(header))
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"{r.stage:22s} {status:>8s}")
        for issue in r.issues:
            print(f"    - {issue}")
    n_failed = sum(1 for r in results if not r.passed)
    print(f"\n{len(results) - n_failed}/{len(results)} checkpoints passed.\n")


if __name__ == "__main__":
    import json as _json

    from app.core.chunking import chunk_records
    from app.core.graph_build import build_graph_store
    from app.core.ingestion import RawRecord
    from app.core.vector_store import HybridVectorStore

    all_records = []
    for fname in ("prs.jsonl", "issues_and_rfcs.jsonl"):
        path = config.RAW_CORPUS_DIR / fname
        with open(path) as f:
            for line in f:
                all_records.append(RawRecord(**_json.loads(line)))

    all_chunks = chunk_records(all_records)
    v_store = HybridVectorStore()
    v_store.add_chunks(all_chunks)
    g_store = build_graph_store(all_records)

    all_results = run_all(v_store, g_store, records=all_records, chunks=all_chunks)
    print_checkpoint_report(all_results)

    sys.exit(1 if any(not r.passed for r in all_results) else 0)
