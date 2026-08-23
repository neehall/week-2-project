"""Pull PRs, issues, RFC threads, and module docs from the GitHub API.

Source: langchain-ai/langchain (see docs/SCOPE.md for corpus scope).

Output: raw records written to data/corpus/raw/ (gitignored — regenerate
by re-running this module rather than committing raw pulls).

Each record keeps the structured metadata the graph is built from later
(app/core/graph_build.py): author, reviewers, linked issues, merge date,
module path. Don't discard this in favor of just the text body.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


REPO = "langchain-ai/langchain"


@dataclass
class RawRecord:
    """One PR, issue, or RFC pulled from the GitHub API, pre-cleaning."""

    kind: str  # "pr" | "issue" | "rfc"
    number: int
    title: str
    body: str
    author: str
    reviewers: list[str] = field(default_factory=list)
    linked_issues: list[int] = field(default_factory=list)
    merged_at: str | None = None
    module_path: str | None = None


def pull_pull_requests(limit: int = 100) -> list[RawRecord]:
    """Pull merged PRs via the GitHub REST/GraphQL API.

    TODO: use PyGithub (see requirements.txt) authenticated with
    os.environ["GITHUB_TOKEN"]. Keep author, reviewers, linked issues, and
    merge date — this is the metadata the graph edges (authored, reviewed,
    merged, decided-in) are built from.
    """
    raise NotImplementedError


def pull_issues_and_rfcs(limit: int = 100) -> list[RawRecord]:
    """Pull issues and RFC-style discussion threads.

    TODO: filter for substantive discussions (not just bug reports) — RFCs
    and design-decision threads are what feeds the decision-provenance
    query type (docs/PLAN.md, query #6).
    """
    raise NotImplementedError


def clean(record: RawRecord) -> RawRecord:
    """Strip markdown boilerplate and bot comments, normalize usernames.

    TODO: strip HTML comments, CI bot signatures, and markdown badges from
    `body`; keep code blocks intact but flagged, so chunking (see
    chunking.py) can split them from prose.
    """
    raise NotImplementedError


if __name__ == "__main__":
    os.makedirs("data/corpus/raw", exist_ok=True)
    # TODO: pull_pull_requests() + pull_issues_and_rfcs(), clean each
    # record, write to data/corpus/raw/*.jsonl
