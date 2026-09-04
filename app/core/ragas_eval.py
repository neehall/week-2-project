"""Ragas-based evaluation -- the standardized-framework counterpart to
evaluation.py's hand-rolled LLM-judge scoring.

evaluation.py's `score_faithfulness`/`score_relevance` are one prompt, one
number, good enough to rank the two arms but not independently validated
(see its own docstring). This module runs the same two properties through
`ragas` instead, as a sanity check that those hand-rolled numbers aren't an
artifact of how that specific judge prompt was worded. It reuses
evaluation.py's `_run_vector_arm`/`_run_graph_arm` for the actual
retrieval + generation, so this never re-runs either arm or spends extra
retrieval/generation tokens -- it only adds a second, independent judge
pass over the same (query, answer, context) triples.

Metrics used (both reference-free -- data/eval/test_queries.json has no
ground-truth answer to score against, only which arm is *expected* to
win):
  - Faithfulness: does every claim in the answer trace back to the
    retrieved context? Ragas' counterpart to evaluation.score_faithfulness.
  - LLMContextPrecisionWithoutReference: is the retrieved context actually
    relevant to the query? Ragas' counterpart to evaluation.score_relevance.

Deliberately skips ResponseRelevancy (ragas' "AnswerRelevancy") -- it
requires an embedding model call per query on top of retrieval's own
embedding calls, and the two metrics above already cover the two
properties this project's eval methodology (docs/PLAN.md) cares about.

Refused queries are skipped here (no answer/context to judge) --
evaluation.py's refusal-test accuracy already covers that behavior.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from app.common import config
from app.core.evaluation import _run_graph_arm, _run_vector_arm

# ragas.metrics still exposes Faithfulness/LLMContextPrecisionWithoutReference
# via this path with a deprecation warning as of ragas 0.4.x (the newer
# ragas.metrics.collections path doesn't have a context-precision-without-
# reference equivalent yet) -- silenced here rather than left to print on
# every eval run.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from ragas import EvaluationDataset, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference


@dataclass
class RagasScore:
    query_id: int
    arm: str  # "vector" | "graph"
    faithfulness: float | None
    context_precision: float | None


def _get_ragas_llm() -> LangchainLLMWrapper:
    # Lazy import -- langchain-anthropic is only needed for this optional
    # eval path, not for the app itself (generation.py uses the plain
    # Anthropic SDK directly).
    from langchain_anthropic import ChatAnthropic

    # Same model as generation.py/evaluation.py's judge. Three fixes below
    # were needed in the Week 3 project's identical LangchainLLMWrapper
    # setup before ragas produced a real score instead of an exception --
    # applied here up front rather than rediscovered the same way:
    #   1. max_tokens=config.GENERATION_MAX_TOKENS, not a smaller ad hoc
    #      value -- ragas' Faithfulness metric is itself multi-step
    #      (decomposes the response into atomic statements, then verifies
    #      each against the context) and needs real headroom.
    #   2. thinking={"type": "disabled"} -- even at a generous max_tokens,
    #      adaptive thinking consumed the whole budget on hidden reasoning
    #      before writing a visible answer (LLMDidNotFinishException) --
    #      the same failure mode this project's own GENERATION_MODEL
    #      comment already documents; ChatAnthropic's lever for it is this
    #      `thinking` field, not the raw Anthropic SDK's
    #      output_config={"effort": "low"} used in generation.py/evaluation.py.
    #   3. bypass_temperature=True below -- ragas' wrapper otherwise sets
    #      langchain_llm.temperature on every call for judge determinism,
    #      but newer Claude models (this one included) reject an explicit
    #      temperature param outright and raise a 400 instead of ignoring it.
    #
    # Not yet run live against this project's own corpus -- see
    # docs/EVAL_RESULTS.md / CODE_MAP.md for status; verified end-to-end in
    # the Week 3 project's identical setup instead (see that project's
    # app/ragas_eval.py and data/sample_deals/ragas_faithfulness_results.json).
    return LangchainLLMWrapper(
        ChatAnthropic(
            model=config.GENERATION_MODEL,
            max_tokens=config.GENERATION_MAX_TOKENS,
            thinking={"type": "disabled"},
        ),
        bypass_temperature=True,
    )


def build_ragas_dataset(
    queries: list[dict], vector_store, graph_store
) -> tuple[EvaluationDataset | None, list[tuple[int, str]]]:
    """Runs both arms on every query and shapes the answered ones into a
    ragas EvaluationDataset. Returns (dataset_or_None, meta) where meta[i]
    is the (query_id, arm) that dataset row i belongs to -- ragas rows
    don't carry arbitrary extra fields, so this list is what maps ragas'
    per-row scores back to a query/arm pair afterwards.
    """
    rows: list[dict] = []
    meta: list[tuple[int, str]] = []

    for q in queries:
        query_text = q["query"]
        vector_score, vector_context = _run_vector_arm(query_text, vector_store)
        graph_score, graph_context = _run_graph_arm(query_text, graph_store)

        for arm_score, context in ((vector_score, vector_context), (graph_score, graph_context)):
            if arm_score.refused or not context:
                continue
            rows.append(
                {
                    "user_input": query_text,
                    "response": arm_score.answer,
                    "retrieved_contexts": [context],
                }
            )
            meta.append((q["id"], arm_score.arm))

    if not rows:
        return None, []
    return EvaluationDataset.from_list(rows), meta


def run_ragas_comparison(queries: list[dict], vector_store, graph_store) -> list[RagasScore]:
    """The ragas-scored counterpart to evaluation.run_comparison().

    Does not re-run checkpoints.run_all() itself -- call that (or
    evaluation.run_comparison()) first if you want the same pre-flight
    sanity checks before spending these judge calls.
    """
    dataset, meta = build_ragas_dataset(queries, vector_store, graph_store)
    if dataset is None:
        return []

    llm = _get_ragas_llm()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = evaluate(
            dataset=dataset,
            metrics=[Faithfulness(), LLMContextPrecisionWithoutReference()],
            llm=llm,
            show_progress=False,
        )
    df = result.to_pandas()

    scores = []
    for (query_id, arm), (_, row) in zip(meta, df.iterrows()):
        scores.append(
            RagasScore(
                query_id=query_id,
                arm=arm,
                faithfulness=_clean(row.get("faithfulness")),
                context_precision=_clean(row.get("llm_context_precision_without_reference")),
            )
        )
    return scores


def _clean(value) -> float | None:
    """ragas returns NaN (not None) for a metric it couldn't score --
    normalize to None so json.dumps() doesn't choke on it downstream."""
    if value is None:
        return None
    try:
        if value != value:  # NaN != NaN
            return None
    except TypeError:
        return None
    return float(value)


def summarize_ragas(scores: list[RagasScore]) -> dict:
    """Per-arm means, in the same shape as evaluation.summarize_results()
    so the two can sit side by side in a report."""
    summary: dict = {}
    for arm in ("vector", "graph"):
        arm_scores = [s for s in scores if s.arm == arm]
        faithfulness = [s.faithfulness for s in arm_scores if s.faithfulness is not None]
        precision = [s.context_precision for s in arm_scores if s.context_precision is not None]
        summary[arm] = {
            "n_scored": len(arm_scores),
            "mean_faithfulness": sum(faithfulness) / len(faithfulness) if faithfulness else None,
            "mean_context_precision": sum(precision) / len(precision) if precision else None,
        }
    return summary
