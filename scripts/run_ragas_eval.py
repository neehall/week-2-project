"""Build both stores from the committed corpus and run the ragas comparison.

Mirrors scripts/run_eval.py's ingestion -> chunking -> store-build sequence,
but scores with app.core.ragas_eval (the `ragas` framework) instead of
evaluation.py's hand-rolled judge, and writes to a separate output file so
neither run overwrites the other:

    PYTHONPATH=. python scripts/run_ragas_eval.py

Cost note: this re-runs retrieval + generation for every query (it does not
reuse scripts/run_eval.py's results.json, since that only stored scores, not
the raw answers/contexts ragas needs) and adds one ragas judge call per
metric per answered query on top. Pass --limit to score a subset first --
the two ragas metrics are reference-free judge calls, similarly priced to
evaluation.py's own _judge() calls, not a new cost category, but still real
spend across all 16 queries x 2 arms x 2 metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.common import config
from app.core.chunking import chunk_records
from app.core.evaluation import load_test_queries
from app.core.graph_build import build_graph_store
from app.core.ingestion import RawRecord
from app.core.ragas_eval import run_ragas_comparison, summarize_ragas
from app.core.vector_store import HybridVectorStore

RESULTS_PATH = config.EVAL_DIR / "ragas_results.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Score only the first N queries (default: all). Useful for a cheap smoke test.",
    )
    args = parser.parse_args()

    all_records = []
    for fname in ("prs.jsonl", "issues_and_rfcs.jsonl"):
        path = config.RAW_CORPUS_DIR / fname
        with open(path) as f:
            for line in f:
                all_records.append(RawRecord(**json.loads(line)))
    print(f"Loaded {len(all_records)} records from {config.RAW_CORPUS_DIR}")

    all_chunks = chunk_records(all_records)
    vector_store = HybridVectorStore()
    vector_store.add_chunks(all_chunks)
    graph_store = build_graph_store(all_records)
    print("Both stores built.")

    queries = load_test_queries()
    if args.limit:
        queries = queries[: args.limit]
    print(f"Running {len(queries)} queries through both arms + ragas scoring...\n")

    scores = run_ragas_comparison(queries, vector_store, graph_store)

    RESULTS_PATH.write_text(json.dumps([asdict(s) for s in scores], indent=2))
    print(f"Wrote {len(scores)} scored results to {RESULTS_PATH}\n")

    summary = summarize_ragas(scores)
    header = f"{'--- Ragas KPIs ---':28s} {'vector':>12s} {'graph':>12s}"
    print(header)
    print("-" * len(header))
    for label, key in (
        ("scored", "n_scored"),
        ("mean faithfulness", "mean_faithfulness"),
        ("mean context precision", "mean_context_precision"),
    ):
        def fmt(v):
            return "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
        print(f"{label:28s} {fmt(summary['vector'][key]):>12s} {fmt(summary['graph'][key]):>12s}")


if __name__ == "__main__":
    main()
