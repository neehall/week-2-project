"""Streamlit page: GraphRAG vs. Vector-RAG head-to-head comparison.

Renders the same numbers as `docs/PROJECT_WRITEUP.md` section 2 /
`docs/EVAL_RESULTS.md`, read live from `data/eval/results.json` (the
`scripts/run_eval.py` output) and `data/eval/test_queries.json`, rather
than a copy-pasted snapshot — so this page always reflects the last real
`evaluation.run_comparison()` run, not whatever the docs said at the time
they were last edited.
"""

import json
import sys
from pathlib import Path

# Each Streamlit page runs as its own top-level script, so it lands on
# sys.path the same way app/Home.py does — needs the repo root added
# explicitly for `from app.common import config` to resolve. See
# app/Home.py's matching comment for why (local run.sh's PYTHONPATH
# export doesn't help here; each page re-executes from scratch).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

from app.common import config

st.set_page_config(page_title="Comparison — GraphRAG vs. Vector-RAG", page_icon="📊")
st.title("GraphRAG vs. Vector-RAG — Head-to-Head")
st.caption(
    "Every query in `data/eval/test_queries.json` runs through both arms "
    "independently, each applying its own refusal rule. See "
    "`docs/PROJECT_WRITEUP.md` (section 2) and `docs/EVAL_RESULTS.md` for "
    "the full write-up."
)

try:
    queries = json.loads(config.TEST_QUERIES_PATH.read_text())
    scores = json.loads((config.EVAL_DIR / "results.json").read_text())
except FileNotFoundError:
    st.error(
        "No eval results found. Run `PYTHONPATH=. python scripts/run_eval.py` "
        "first (needs `ANTHROPIC_API_KEY` in `.env`)."
    )
    st.stop()

by_query: dict[int, dict[str, dict]] = {}
for s in scores:
    by_query.setdefault(s["query_id"], {})[s["arm"]] = s

# --- KPI summary, computed the same way evaluation.summarize_results() does ---
st.subheader("Observability KPIs")


def _kpi_row(arm: str) -> dict:
    arm_scores = [s for s in scores if s["arm"] == arm]
    answered = [s for s in arm_scores if not s["refused"]]
    refusal_tests = [s for s in arm_scores if s["correctly_refused"] is not None]
    latencies = sorted(s["latency_seconds"] for s in arm_scores)

    def _mean(vals):
        return round(sum(vals) / len(vals), 3) if vals else None

    def _p95(vals):
        if not vals:
            return None
        idx = min(len(vals) - 1, round(0.95 * (len(vals) - 1)))
        return vals[idx]

    return {
        "arm": arm,
        "queries run": len(arm_scores),
        "answered": len(answered),
        "refused": len(arm_scores) - len(answered),
        "mean faithfulness": _mean([s["faithfulness"] for s in answered]),
        "mean relevance": _mean([s["relevance"] for s in answered]),
        "refusal-test accuracy": _mean(
            [1.0 if s["correctly_refused"] else 0.0 for s in refusal_tests]
        ),
        "mean latency (s)": _mean(latencies),
        "p95 latency (s)": _p95(latencies),
    }


kpi_df = pd.DataFrame([_kpi_row("vector"), _kpi_row("graph")]).set_index("arm")
st.dataframe(kpi_df.T, use_container_width=True)

# --- Per-query breakdown ---
st.subheader("Per-query results")

rows = []
for q in queries:
    qid = q["id"]
    v = by_query.get(qid, {}).get("vector")
    g = by_query.get(qid, {}).get("graph")
    rows.append(
        {
            "#": qid,
            "type": q["type"],
            "query": q["query"] or "(empty)",
            "expected": q["expected_edge"],
            "refusal test": q.get("is_refusal_test", False),
            "vector": "✅ answered" if v and not v["refused"] else "❌ refused",
            "vector faith/rel": f"{v['faithfulness']:.2f}/{v['relevance']:.2f}"
            if v and not v["refused"]
            else "—",
            "graph": "✅ answered" if g and not g["refused"] else "❌ refused",
            "graph faith/rel": f"{g['faithfulness']:.2f}/{g['relevance']:.2f}"
            if g and not g["refused"]
            else "—",
        }
    )

st.dataframe(pd.DataFrame(rows).set_index("#"), use_container_width=True)

with st.expander("Full answer text per query"):
    for q in queries:
        qid = q["id"]
        v = by_query.get(qid, {}).get("vector")
        g = by_query.get(qid, {}).get("graph")
        st.markdown(f"**{qid}. {q['type']}** — _{q['query'] or '(empty)'}_")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("Vector arm")
            st.markdown(v["answer"] if v and v["answer"] else "_(refused / no answer)_")
        with col2:
            st.markdown("Graph arm")
            st.markdown(g["answer"] if g and g["answer"] else "_(refused / no answer)_")
        st.divider()
