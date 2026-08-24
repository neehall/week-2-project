"""Central place for project-wide settings, so every module reads the same
values instead of scattering literals. See docs/PLAN.md and docs/SCOPE.md
for the reasoning behind these numbers.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env into the process environment on first import of this module, so
# every other module can just read os.environ (via github_token() etc.)
# without each having to remember to call load_dotenv() itself. No-ops
# quietly if .env doesn't exist yet.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# On Streamlit Community Cloud, secrets are configured via the app's web
# UI and only reachable through st.secrets — they are NOT injected into
# os.environ automatically. Bridge them in here so every module can keep
# reading os.environ (via anthropic.Anthropic(), github_token(), etc.)
# regardless of whether this is running locally (.env) or deployed.
# Guarded so this is a silent no-op outside a running Streamlit app.
try:
    import streamlit as st

    for _key in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN"):
        if _key not in os.environ and _key in st.secrets:
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass

# --- Corpus -----------------------------------------------------------------

GITHUB_REPO = "langchain-ai/langchain"
# Small by default so iterating on chunking/graph_build/retrieval doesn't
# require a full multi-hundred-request ingestion run each time. Override via
# env for the final full pull (see run.sh / .env.example).
PR_LIMIT = int(os.environ.get("PR_LIMIT", "20"))
ISSUE_LIMIT = int(os.environ.get("ISSUE_LIMIT", "20"))

# Wall-clock ceiling for one ingestion pull (pull_pull_requests or
# pull_issues_and_rfcs), independent of PR_LIMIT/ISSUE_LIMIT — protects
# against `get_pulls()`/`get_issues()` paging through a huge closed/updated
# history without ever finding `limit` matching records (e.g. filters
# rarely matching). Returns whatever was collected so far rather than
# hanging indefinitely.
INGESTION_TIME_BUDGET_SECONDS = int(os.environ.get("INGESTION_TIME_BUDGET_SECONDS", "120"))

# Per-request timeout and retry for the GitHub client — PyGithub's default
# client has no timeout, so a stalled connection hangs rather than failing
# fast. See _client() in ingestion.py.
GITHUB_REQUEST_TIMEOUT_SECONDS = 15
GITHUB_REQUEST_RETRIES = 3

# --- Paths --------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_CORPUS_DIR = DATA_DIR / "corpus" / "raw"
EVAL_DIR = DATA_DIR / "eval"
TEST_QUERIES_PATH = EVAL_DIR / "test_queries.json"

# --- Chunking / embedding ------------------------------------------------

# Local embedding model (sentence-transformers, no API key needed) — swap
# for text-embedding-3-small (1536-dim, via Nebius) once NEBIUS_API_KEY is
# set; see docs/PLAN.md's chunk-size-to-embedding-capacity table for both.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
CHUNK_SIZE_TOKENS = 250       # midpoint of the 200-300 recommended range for 384-dim
CHUNK_OVERLAP_TOKENS = 50

# --- Retrieval ------------------------------------------------------------

VECTOR_TOP_K = 5              # final top-k after fusion + rerank
RERANK_CANDIDATE_POOL = 20    # width of the pre-rerank candidate set
GRAPH_MAX_HOPS = 2

# --- Generation ---------------------------------------------------------

# Claude via the official Anthropic SDK — generation.py. Chosen over the
# original Nebius-hosted default since NEBIUS_API_KEY isn't set; needs
# ANTHROPIC_API_KEY in .env instead. See docs/PLAN.md's generation section.
# 1024 was too small once the corpus grew to 200 records — an aggregation
# answer over a large subgraph got cut off mid-word. Fixed by bumping to
# 4096 at the time — but that broke again at 1000 records: a subgraph can
# now run 50K+ chars (e.g. "list every contributor to module X" against a
# module with 30+ PRs), and Claude Opus 5's adaptive thinking consumed the
# entire 4096-token budget on hidden reasoning, leaving stop_reason
# "max_tokens" and zero visible output — worse than truncation, a fully
# empty answer. Bumped again with real headroom, and generation.py caps
# reasoning effort so more of the budget goes to the visible answer
# instead of unbounded thinking (same fix already applied to
# evaluation._judge() for the same underlying failure mode). This is a
# stopgap, not a permanent fix — subgraph size scales with corpus size and
# will eventually outgrow any static token budget; the real fix is
# capping/summarizing large subgraphs before they reach generation
# (not done here — see docs/EVAL_RESULTS.md).
GENERATION_MODEL = "claude-opus-5"
GENERATION_MAX_TOKENS = 8192

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
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
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
