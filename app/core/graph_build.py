"""Extract entities/relationships from the cleaned corpus and build the graph.

See docs/SCOPE.md, "Graph schema (20+ nodes required)":
- Node types: contributors, PRs, issues/RFCs, modules/packages, skills
- Edge types: authored, reviewed, merged, discusses, decided-in, uses

"Skills" (people/projects/skills/documents/decisions, per the original
project brief) map onto this GitHub-repo domain as the tools/technologies
a PR touches — provider integrations (openai, anthropic, deepseek, ...)
recovered from conventional-commit title scopes, and libraries recovered
from Dependabot-style "bump X from A to B" titles. See
_extract_skills() below. A contributor's tools are then a 2-hop graph
traversal away (contributor -authored-> pr -uses-> skill), same as any
other multi-hop query — no direct contributor-skill edge is needed.

Uses the same cleaned records as the vector arm (see ingestion.py) but
builds a separate index — the two arms don't share state at query time, so
the 10-query comparison (docs/PLAN.md) is measuring a real difference.

Graph store: NetworkX in-memory by default (no server needed). Swap for
Neo4j by passing backend="neo4j" and setting NEO4J_URI/USER/PASSWORD in
.env — the node/edge schema stays the same either way, but the Neo4j path
isn't implemented yet (see GraphStore).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# Known tools/technologies worth surfacing as "skill" nodes — provider
# integrations this repo's PRs actually touch (seen as conventional-commit
# title scopes, e.g. "fix(anthropic): ...") plus a few common libraries/
# infra terms that show up in dependency-bump titles or body text.
#
# Deliberately excludes "langchain" itself: it's a valid conventional-
# commit scope in this corpus, but it's also the name of the product
# every query is implicitly about — including it caused a real false
# positive (query 9's refusal test, "Who approved LangChain's pricing
# model?", matched skill:langchain purely because the product's own name
# appeared in the question, and the graph arm answered instead of
# refusing). A "skill" node should represent something distinct from the
# repo itself, not the repo's own name.
KNOWN_SKILLS = {
    "openai", "anthropic", "deepseek", "fireworks", "mistralai", "openrouter",
    "xai", "perplexity", "huggingface", "exa", "nomic", "langgraph",
    "pydantic", "fastapi", "docker", "redis", "postgres",
    "pytest", "asyncio", "graphql", "grpc", "websocket", "typescript", "rust",
}

_SCOPE_RE = re.compile(r"^\w+\(([^)]+)\):")
_BUMP_RE = re.compile(r"\bbump\s+([a-zA-Z][\w.-]*)\s+from\b", re.IGNORECASE)


@dataclass
class Node:
    id: str
    type: str  # "contributor" | "pr" | "issue" | "rfc" | "module" | "skill"
    properties: dict = field(default_factory=dict)


@dataclass
class Edge:
    source_id: str
    target_id: str
    type: str  # "authored" | "reviewed" | "merged" | "discusses" | "decided_in" | "uses"
    properties: dict = field(default_factory=dict)


class GraphStore:
    def __init__(self, backend: str = "networkx"):
        self.backend = backend
        if backend == "networkx":
            import networkx as nx

            self._graph = nx.MultiDiGraph()
        elif backend == "neo4j":
            # TODO: connect via neo4j.GraphDatabase.driver(...) using
            # NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD from .env (app.common.config).
            # Node/Edge dataclasses above map 1:1 onto Cypher MERGE statements;
            # not needed for this project since NetworkX covers the eval.
            raise NotImplementedError("neo4j backend not implemented — use 'networkx'")
        else:
            raise ValueError(f"unknown backend: {backend!r}")

    def add_node(self, node: Node) -> None:
        self._graph.add_node(node.id, type=node.type, **node.properties)

    def add_edge(self, edge: Edge) -> None:
        # MultiDiGraph keyed by edge type so re-adding the same
        # (source, target, type) triple updates rather than duplicates.
        self._graph.add_edge(
            edge.source_id, edge.target_id, key=edge.type, type=edge.type, **edge.properties
        )

    def node_count(self) -> int:
        """Used to confirm the 20+ node requirement is met before submitting."""
        return self._graph.number_of_nodes()

    def get_node(self, node_id: str) -> dict | None:
        if node_id not in self._graph.nodes:
            return None
        return dict(self._graph.nodes[node_id])

    def node_ids_by_type(self, type_: str) -> list[str]:
        return [n for n, attrs in self._graph.nodes(data=True) if attrs.get("type") == type_]

    def ego_subgraph(self, seed_node_ids, max_hops: int):
        """The induced subgraph within max_hops of any seed node.

        Traverses as undirected (reviewer<->PR, PR<->module edges should
        be reachable in either direction for query purposes) but the
        returned subgraph keeps original edge direction/type for
        serialization.
        """
        import networkx as nx

        undirected = self._graph.to_undirected(as_view=True)
        nodes_in_scope: set[str] = set()
        for seed_id in seed_node_ids:
            if seed_id in undirected:
                ego = nx.ego_graph(undirected, seed_id, radius=max_hops)
                nodes_in_scope.update(ego.nodes)
        return self._graph.subgraph(nodes_in_scope)


def _infer_module_path(record, known_modules: list[str]) -> str | None:
    """Issues/RFCs don't carry a file-diff-derived module_path (only PRs
    do — see ingestion.py). Fall back to keyword matching the record's
    text against the vocabulary of module names actually seen in the PRs,
    so issue/RFC nodes can still get a "discusses"/"decided_in" edge to a
    module rather than floating disconnected.
    """
    if not known_modules:
        return None
    text = f"{record.title}\n{record.body}".lower()
    counts = Counter()
    for module in known_modules:
        hits = text.count(module.lower())
        if hits:
            counts[module] = hits
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _extract_skills(record) -> set[str]:
    """Recover the tools/technologies a record touches.

    Two sources, both grounded in real conventions this corpus actually
    uses (not a free-text keyword scan of arbitrary prose):
      - Conventional-commit title scopes, e.g. "fix(anthropic): ..." or
        "chore(mistralai,exa,nomic): ..." — intersected with KNOWN_SKILLS
        so internal-only scopes (module names like "core", "infra") don't
        get promoted to "skill" nodes.
      - Dependabot-style "Bumps X from A to B" / "bump X from A to B"
        titles — the bumped dependency name is a tool by definition, kept
        regardless of KNOWN_SKILLS membership.
    """
    skills: set[str] = set()

    scope_match = _SCOPE_RE.match(record.title)
    if scope_match:
        for scope in scope_match.group(1).split(","):
            scope = scope.strip().lower()
            if scope in KNOWN_SKILLS:
                skills.add(scope)

    bump_match = _BUMP_RE.search(record.title)
    if bump_match:
        skills.add(bump_match.group(1).lower())

    return skills


def extract_entities_and_relations(records: list) -> tuple[list[Node], list[Edge]]:
    """Turn cleaned records (ingestion.py) into nodes and edges.

    - one Node per unique contributor (author + every reviewer)
    - one Node per PR/issue/RFC, one Node per module touched
    - one Node per tool/technology touched (see _extract_skills())
    - Edge(contributor -authored-> pr/issue/rfc)
    - Edge(contributor -reviewed-> pr/issue/rfc)
    - Edge(pr -merged-> module)
    - Edge(rfc -decided_in-> module)
    - Edge(issue -discusses-> module)   (issues don't "merge" or "decide")
    - Edge(record -uses-> skill)
    - Edge(record -discusses-> record)  for linked_issues that resolve to
      another record actually present in this corpus (a linked issue
      outside the pulled set has nothing to point at)
    """
    nodes: dict[str, Node] = {}

    def add_node(node_id: str, type_: str, properties: dict) -> None:
        nodes.setdefault(node_id, Node(id=node_id, type=type_, properties=properties))

    known_modules = sorted({r.module_path for r in records if r.kind == "pr" and r.module_path})
    record_node_id = {r.number: f"{r.kind}:{r.number}" for r in records}

    edges: list[Edge] = []

    for r in records:
        record_id = f"{r.kind}:{r.number}"
        add_node(record_id, r.kind, {"title": r.title, "merged_at": r.merged_at})

        author_id = f"contributor:{r.author}"
        add_node(author_id, "contributor", {})
        edges.append(Edge(author_id, record_id, "authored"))

        for reviewer in r.reviewers:
            reviewer_id = f"contributor:{reviewer}"
            add_node(reviewer_id, "contributor", {})
            edges.append(Edge(reviewer_id, record_id, "reviewed"))

        module_path = r.module_path or _infer_module_path(r, known_modules)
        if module_path:
            module_id = f"module:{module_path}"
            add_node(module_id, "module", {})
            edge_type = {"pr": "merged", "rfc": "decided_in", "issue": "discusses"}[r.kind]
            edges.append(Edge(record_id, module_id, edge_type))

        for skill in _extract_skills(r):
            skill_id = f"skill:{skill}"
            add_node(skill_id, "skill", {})
            edges.append(Edge(record_id, skill_id, "uses"))

        for linked_number in r.linked_issues:
            target_id = record_node_id.get(linked_number)
            if target_id and target_id != record_id:
                edges.append(Edge(record_id, target_id, "discusses"))

    return list(nodes.values()), edges


def build_graph_store(records: list, backend: str = "networkx") -> GraphStore:
    """Convenience wrapper: extract, then load into a fresh GraphStore."""
    nodes, edges = extract_entities_and_relations(records)
    store = GraphStore(backend=backend)
    for node in nodes:
        store.add_node(node)
    for edge in edges:
        store.add_edge(edge)
    return store
