"""Pull PRs, issues, RFC threads, and module docs from the GitHub API.

Source: langchain-ai/langchain (see docs/SCOPE.md for corpus scope).

Output: raw records written to data/corpus/raw/ (gitignored — regenerate
by re-running this module rather than committing raw pulls).

Each record keeps the structured metadata the graph is built from later
(app/core/graph_build.py): author, reviewers, linked issues, merge date,
module path. Don't discard this in favor of just the text body.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from github import Auth, Github, GithubException

from app.common import config

# Bot-authored comments/reviews to drop during cleaning — CI and release
# bots don't represent human decisions the graph cares about.
BOT_SUFFIXES = ("[bot]",)

# "Fixes #123", "Closes #123", "Related to #123", etc. — used to recover
# linked-issue edges when the API's own linkage misses informal references.
_ISSUE_REF_RE = re.compile(
    r"\b(?:fixes|closes|resolves|related to|see)\s+#(\d+)", re.IGNORECASE
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


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


def _client() -> Github:
    token = config.github_token()
    if token:
        return Github(auth=Auth.Token(token))
    return Github()  # unauthenticated: 60 req/hr, smoke-testing only


def _linked_issue_numbers(body: str) -> list[int]:
    return sorted({int(n) for n in _ISSUE_REF_RE.findall(body or "")})


def _dominant_module_path(paths: list[str]) -> str | None:
    """The most-touched top-level module a PR's changed files fall under,
    e.g. "libs/core/langchain_core/memory" -> "memory". Used to build the
    PR/issue -> module edges in the graph (docs/SCOPE.md's schema).
    """
    modules = []
    for path in paths:
        parts = path.split("/")
        # langchain-ai/langchain layout: libs/<package>/langchain_*/<module>/...
        for marker in ("langchain_core", "langchain", "langchain_community"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    modules.append(parts[idx + 1])
                break
    if not modules:
        return None
    return Counter(modules).most_common(1)[0][0]


def pull_pull_requests(limit: int = config.PR_LIMIT) -> list[RawRecord]:
    """Pull merged PRs via the GitHub REST API (PyGithub).

    Keeps author, reviewers, linked issues, and merge date — this is the
    metadata the graph edges (authored, reviewed, merged, decided-in) are
    built from.
    """
    gh = _client()
    repo = gh.get_repo(config.GITHUB_REPO)
    pulls = repo.get_pulls(state="closed", sort="updated", direction="desc")

    records: list[RawRecord] = []
    for pr in pulls:
        if len(records) >= limit:
            break
        if pr.merged_at is None:
            continue  # closed-without-merge: no decision was actually made

        try:
            reviewers = sorted(
                {
                    review.user.login
                    for review in pr.get_reviews()
                    if review.user is not None
                }
            )
            module_path = _dominant_module_path([f.filename for f in pr.get_files()])
        except GithubException:
            # Rate-limited or file list too large for a huge PR — keep the
            # record with what we have rather than dropping it entirely.
            reviewers, module_path = [], None

        records.append(
            RawRecord(
                kind="pr",
                number=pr.number,
                title=pr.title or "",
                body=pr.body or "",
                author=pr.user.login if pr.user else "unknown",
                reviewers=reviewers,
                linked_issues=_linked_issue_numbers(pr.body or ""),
                merged_at=pr.merged_at.isoformat(),
                module_path=module_path,
            )
        )
    return records


def pull_issues_and_rfcs(limit: int = config.ISSUE_LIMIT) -> list[RawRecord]:
    """Pull issues and RFC-style discussion threads.

    Filters for substantive discussions (not one-line bug reports) — RFCs
    and design-decision threads are what feeds the decision-provenance
    query type (docs/PLAN.md, query #6).
    """
    gh = _client()
    repo = gh.get_repo(config.GITHUB_REPO)
    issues = repo.get_issues(state="all", sort="updated", direction="desc")

    records: list[RawRecord] = []
    for issue in issues:
        if len(records) >= limit:
            break
        if issue.pull_request is not None:
            continue  # the issues endpoint also returns PRs; skip those

        body = issue.body or ""
        if len(body) < 200:
            continue  # too short to be a substantive discussion

        labels = {label.name.lower() for label in issue.labels}
        kind = "rfc" if any("rfc" in l or "discussion" in l for l in labels) else "issue"

        records.append(
            RawRecord(
                kind=kind,
                number=issue.number,
                title=issue.title or "",
                body=body,
                author=issue.user.login if issue.user else "unknown",
                reviewers=sorted({a.login for a in issue.assignees}),
                linked_issues=_linked_issue_numbers(body),
                merged_at=None,
                module_path=None,  # inferred at graph-build time from labels/body
            )
        )
    return records


def clean(record: RawRecord) -> RawRecord:
    """Strip markdown boilerplate and bot noise, normalize usernames.

    Keeps code blocks intact (fenced ``` blocks pass through unchanged) so
    chunking.py can later split them from prose rather than clean.py
    mangling the identifiers dense retrieval needs.
    """
    if record.author.endswith(BOT_SUFFIXES):
        record.author = "unknown"  # don't attribute human decisions to bots
    record.reviewers = [r for r in record.reviewers if not r.endswith(BOT_SUFFIXES)]

    body = _HTML_COMMENT_RE.sub("", record.body)
    # Drop common CI/release-bot signature lines without touching fenced
    # code blocks — split on ``` fences and only clean the prose segments.
    segments = body.split("```")
    for i in range(0, len(segments), 2):  # even indices = prose, odd = code
        lines = segments[i].splitlines()
        lines = [ln for ln in lines if "[bot]" not in ln.lower()]
        segments[i] = "\n".join(lines)
    record.body = "```".join(segments).strip()

    return record


def _write_jsonl(records: list[RawRecord], path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(asdict(record)) + "\n")


def run(pr_limit: int = config.PR_LIMIT, issue_limit: int = config.ISSUE_LIMIT) -> None:
    prs = [clean(r) for r in pull_pull_requests(pr_limit)]
    issues = [clean(r) for r in pull_issues_and_rfcs(issue_limit)]

    _write_jsonl(prs, config.RAW_CORPUS_DIR / "prs.jsonl")
    _write_jsonl(issues, config.RAW_CORPUS_DIR / "issues_and_rfcs.jsonl")

    print(f"Pulled {len(prs)} PRs -> {config.RAW_CORPUS_DIR / 'prs.jsonl'}")
    print(
        f"Pulled {len(issues)} issues/RFCs -> "
        f"{config.RAW_CORPUS_DIR / 'issues_and_rfcs.jsonl'}"
    )


if __name__ == "__main__":
    run()
