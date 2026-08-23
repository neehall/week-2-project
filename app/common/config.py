"""Central place for project-wide settings, so every module reads the same
values instead of scattering literals. See docs/PLAN.md and docs/SCOPE.md
for the reasoning behind these numbers.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Corpus -----------------------------------------------------------------

GITHUB_REPO = "langchain-ai/langchain"
PR_LIMIT = 100
ISSUE_LIMIT = 100

# --- Paths --------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_CORPUS_DIR = DATA_DIR / "corpus" / "raw"
EVAL_DIR = DATA_DIR / "eval"
TEST_QUERIES_PATH = EVAL_DIR / "test_queries.json"

# --- Chunking / embedding ------------------------------------------------

# Default embedding model is text-embedding-3-small-equivalent (1536-dim) via
# Nebius; see docs/PLAN.md's chunk-size-to-embedding-capacity table.
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
CHUNK_SIZE_TOKENS = 500       # midpoint of the 400-600 recommended range
CHUNK_OVERLAP_TOKENS = 50

# --- Retrieval ------------------------------------------------------------

VECTOR_TOP_K = 5              # final top-k after fusion + rerank
RERANK_CANDIDATE_POOL = 20    # width of the pre-rerank candidate set
GRAPH_MAX_HOPS = 2

# --- Confidence gate --------------------------------------------------------

# Below this reranked similarity score, the vector arm refuses rather than
# answering on weak evidence. Starting point — tune against the 10-query
# comparison set (docs/PLAN.md) once real scores are observed.
VECTOR_CONFIDENCE_THRESHOLD = 0.5

REFUSAL_MESSAGE = (
    "I couldn't find this in the LangChain repo data I've indexed. Try "
    "rephrasing, or this may be outside what I've ingested."
)

# --- Env var names (values live in .env, never here) ------------------------

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
NEBIUS_API_KEY_ENV = "NEBIUS_API_KEY"
NEBIUS_BASE_URL_ENV = "NEBIUS_BASE_URL"
NEO4J_URI_ENV = "NEO4J_URI"
NEO4J_USER_ENV = "NEO4J_USER"
NEO4J_PASSWORD_ENV = "NEO4J_PASSWORD"


def github_token() -> str | None:
    """The GitHub PAT from .env, or None to fall back to unauthenticated
    (rate-limited to 60 req/hr) — fine for a quick smoke test, not for a
    full ingestion run.
    """
    return os.environ.get(GITHUB_TOKEN_ENV) or None
