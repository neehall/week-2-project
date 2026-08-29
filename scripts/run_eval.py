"""Build both stores from the committed corpus and run the full comparison.

Mirrors the __main__ block at the bottom of app/core/checkpoints.py (same
ingestion → chunking → store-build sequence) but goes one step further:
runs evaluation.run_comparison() over data/eval/test_queries.json and
writes the scored output to data/eval/results.json — the file
docs/EVAL_RESULTS.md's tables are generated from.

Not committed previously; earlier runs (see git log on data/eval/
results.json) were driven ad hoc. Adding this so the run is reproducible:

    PYTHONPATH=. python scripts/run_eval.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.common import config
from app.core.chunking import chunk_records
from app.core.evaluation import load_test_queries, run_comparison
from app.core.graph_build import build_graph_store
from app.core.ingestion import RawRecord
from app.core.vector_store import HybridVectorStore

RESULTS_PATH = config.EVAL_DIR / "results.json"


def main() -> None:
    all_records = []
    for fname in ("prs.jsonl", "issues_and_rfcs.jsonl"):
        path = config.RAW_CORPUS_DIR / fname
        with open(path) as f:
            for line in f:
                all_records.append(RawRecord(**json.loads(line)))

    print(f"Loaded {len(all_records)} records from {config.RAW_CORPUS_DIR}")

    all_chunks = chunk_records(all_records)
    print(f"Chunked into {len(all_chunks)} chunks")

    vector_store = HybridVectorStore()
    vector_store.add_chunks(all_chunks)
    graph_store = build_graph_store(all_records)
    print("Both stores built.")

    queries = load_test_queries()
    print(f"Running {len(queries)} queries through both arms...\n")

    scores = run_comparison(
        queries, vector_store, graph_store, records=all_records, chunks=all_chunks
    )

    RESULTS_PATH.write_text(json.dumps([asdict(s) for s in scores], indent=2))
    print(f"\nWrote {len(scores)} scored results to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
