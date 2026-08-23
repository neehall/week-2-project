# Changelog

All notable changes to this project are logged here, newest first. This is
the versioning record for the project — `docs/PLAN.md` and `docs/SCOPE.md`
are the living design docs; this file tracks what changed and when.

## [Unreleased]

### Added
- Initial project scaffold: `README.md`, `requirements.txt`, `.env.example`,
  `run.sh`, `.gitignore`.
- `docs/SCOPE.md` — corpus choice, one-liner primer, filled-out framework.
- `docs/PLAN.md` — architecture, chunking/embedding sizing, hybrid retrieval
  design, refusal path, 10-query comparison set, eval methodology, build
  sequence. Full interactive version published as a Claude artifact (linked
  in the doc).
- `app/core/` module skeletons: ingestion, chunking, graph_build,
  vector_store, retrieval_vector, retrieval_graph, confidence_gate,
  generation, evaluation.
- `app/graph_flow.py` — LangGraph state machine skeleton wiring both
  retrieval arms through the confidence gate.
- `data/eval/test_queries.json` — the 10-query comparison set.
