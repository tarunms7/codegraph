"""PageRank-based file ranking with task-aware personalization."""

from __future__ import annotations

import logging

import networkx as nx

logger = logging.getLogger("codegraph")


def rank_files(
    graph: nx.MultiDiGraph,
    personalization: dict[str, float] | None = None,
    alpha: float = 0.85,
) -> dict[str, float]:
    """Rank files by importance using PageRank.

    Returns a dict mapping file path → rank score, sorted descending by score.
    """
    if graph.number_of_nodes() == 0:
        return {}

    nodes = list(graph.nodes())
    if len(nodes) == 1:
        return {nodes[0]: 1.0}

    # Convert MultiDiGraph → DiGraph with weight = number of multi-edges
    simple = nx.DiGraph()
    simple.add_nodes_from(graph.nodes())
    for u, v, _data in graph.edges(data=True):
        if simple.has_edge(u, v):
            simple[u][v]["weight"] += 1
        else:
            simple.add_edge(u, v, weight=1)

    # If personalization is provided, ensure all graph nodes are present
    if personalization is not None:
        full_p: dict[str, float] = {}
        for node in simple.nodes():
            full_p[node] = personalization.get(node, 0.0)
        # If all values are zero, fall back to global ranking
        if sum(full_p.values()) == 0:
            full_p = None  # type: ignore[assignment]
        personalization = full_p

    try:
        scores = nx.pagerank(simple, alpha=alpha, personalization=personalization, weight="weight")
    except nx.PowerIterationFailedConvergence:
        logger.warning("PageRank did not converge, using uniform ranking")
        score = 1.0 / len(nodes)
        scores = {n: score for n in nodes}

    # Sort descending by score
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


def personalization_for_files(files: list[str], graph: nx.MultiDiGraph) -> dict[str, float] | None:
    """Create a personalization vector biased toward specific files.

    Task files get 1.0, all others get 0.0.
    Returns None if no files match graph nodes.
    """
    graph_nodes = set(graph.nodes())
    matched = [f for f in files if f in graph_nodes]
    if not matched:
        return None

    p: dict[str, float] = {n: 0.0 for n in graph_nodes}
    for f in matched:
        p[f] = 1.0
    return p


def personalization_for_query(query: str, graph: nx.MultiDiGraph) -> dict[str, float] | None:
    """Create a personalization vector from a natural language query.

    Tokenize query into keywords; match against file paths and symbol names.
    Matched files get weight = keyword match count. Returns None if no matches.
    """
    keywords = query.lower().split()
    if not keywords:
        return None

    scores: dict[str, float] = {}
    for node in graph.nodes():
        data = graph.nodes[node]
        file_info = data.get("file_info")

        match_count = 0
        node_lower = node.lower()
        for kw in keywords:
            if kw in node_lower:
                match_count += 1

        # Check symbol names
        if file_info is not None:
            for sym in file_info.symbols:
                name_lower = sym.name.lower()
                for kw in keywords:
                    if kw in name_lower:
                        match_count += 1

        if match_count > 0:
            scores[node] = float(match_count)

    if not scores:
        return None

    # Build full personalization vector
    p: dict[str, float] = {n: 0.0 for n in graph.nodes()}
    p.update(scores)
    return p
