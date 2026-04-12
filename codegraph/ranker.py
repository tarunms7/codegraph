"""Ranking helpers for repo maps and task-aware retrieval."""

from __future__ import annotations

import logging
import math
import re
from collections import deque

import networkx as nx

from codegraph.models import EdgeKind

logger = logging.getLogger("codegraph")

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")

_EDGE_WEIGHTS: dict[str, float] = {
    EdgeKind.TESTS.value: 1.25,
    EdgeKind.IMPORTS.value: 1.0,
    EdgeKind.CALLS.value: 0.9,
    EdgeKind.USES_TYPE.value: 0.8,
    EdgeKind.INHERITS.value: 0.75,
    EdgeKind.IMPLEMENTS.value: 0.75,
}

_TEST_HINT_TOKENS = {"test", "tests", "spec", "specs", "pytest", "unittest"}


def _compact_text(text: str) -> str:
    """Normalize text for exact code-shaped matching."""
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _stem_from_path(path: str) -> str:
    """Return basename without extension."""
    basename = path.rsplit("/", 1)[-1]
    return basename.rsplit(".", 1)[0]


def _keywords_in_order(tokens: list[str], keywords: list[str]) -> bool:
    """Check whether keywords appear in order inside a token sequence."""
    if not keywords:
        return False

    index = 0
    for token in tokens:
        if token == keywords[index]:
            index += 1
            if index == len(keywords):
                return True
    return False


def _to_simple_digraph(graph: nx.MultiDiGraph) -> nx.DiGraph:
    """Convert a MultiDiGraph to a weighted DiGraph."""
    simple = nx.DiGraph()
    simple.add_nodes_from(graph.nodes(data=True))
    for u, v, data in graph.edges(data=True):
        edge_kind = str(data.get("kind", EdgeKind.IMPORTS.value))
        weight = _EDGE_WEIGHTS.get(edge_kind, 1.0)
        if simple.has_edge(u, v):
            simple[u][v]["weight"] += weight
        else:
            simple.add_edge(u, v, weight=weight)
    return simple


def _normalize_personalization(
    graph: nx.DiGraph,
    personalization: dict[str, float] | None,
) -> dict[str, float] | None:
    """Expand a sparse personalization mapping to all nodes and normalize it."""
    if personalization is None:
        return None

    full_p: dict[str, float] = {}
    for node in graph.nodes():
        full_p[node] = max(0.0, float(personalization.get(node, 0.0)))

    total = sum(full_p.values())
    if total <= 0:
        return None
    return {node: value / total for node, value in full_p.items()}


def _pagerank_power_iteration(
    graph: nx.DiGraph,
    personalization: dict[str, float] | None = None,
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-6,
) -> dict[str, float]:
    """Pure-Python weighted PageRank.

    NetworkX's public ``pagerank`` route may delegate to SciPy-backed code.
    For codegraph we want a dependency-safe implementation that behaves the
    same way on bare Python installs.
    """
    nodes = list(graph.nodes())
    if not nodes:
        return {}
    if len(nodes) == 1:
        return {nodes[0]: 1.0}

    p = _normalize_personalization(graph, personalization)
    if p is None:
        uniform = 1.0 / len(nodes)
        p = {node: uniform for node in nodes}

    x = p.copy()
    out_weight = {
        node: sum(float(data.get("weight", 1.0)) for _, _, data in graph.out_edges(node, data=True))
        for node in nodes
    }
    dangling = [node for node, weight in out_weight.items() if weight <= 0.0]

    for _ in range(max_iter):
        x_last = x.copy()
        x = {node: (1.0 - alpha) * p[node] for node in nodes}

        dangling_sum = alpha * sum(x_last[node] for node in dangling)
        if dangling_sum:
            for node in nodes:
                x[node] += dangling_sum * p[node]

        for src in nodes:
            total_out = out_weight[src]
            if total_out <= 0.0:
                continue
            share = alpha * x_last[src] / total_out
            for _, tgt, data in graph.out_edges(src, data=True):
                x[tgt] += share * float(data.get("weight", 1.0))

        error = sum(abs(x[node] - x_last[node]) for node in nodes)
        if error < len(nodes) * tol:
            break
    else:
        logger.warning("PageRank did not converge, using last iteration result")

    total = sum(x.values())
    if total > 0:
        x = {node: value / total for node, value in x.items()}
    return x


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    """Normalize arbitrary non-negative scores into [0, 1]."""
    if not scores:
        return {}
    max_score = max(scores.values())
    if max_score <= 0:
        return {node: 0.0 for node in scores}
    return {node: value / max_score for node, value in scores.items()}


def _combine_scores(*weighted_scores: tuple[float, dict[str, float]]) -> dict[str, float]:
    """Combine multiple score maps with weights."""
    combined: dict[str, float] = {}
    for weight, scores in weighted_scores:
        if weight == 0 or not scores:
            continue
        for node, score in scores.items():
            combined[node] = combined.get(node, 0.0) + (weight * score)
    return combined


def _is_probable_test_path(path: str) -> bool:
    lower = path.lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        "/tests/" in lower
        or "/__tests__/" in lower
        or basename.startswith("test_")
        or basename.endswith("_test.py")
        or ".test." in basename
        or ".spec." in basename
    )


def _tokenize(text: str) -> list[str]:
    """Tokenize paths, symbols, and queries in a retrieval-friendly way."""
    raw_tokens = _TOKEN_RE.findall(text)
    tokens: list[str] = []
    for token in raw_tokens:
        lowered = token.lower()
        if lowered:
            tokens.append(lowered)
        if "_" in token:
            tokens.extend(part.lower() for part in token.split("_") if part)
        if any(ch.isupper() for ch in token[1:]):
            tokens.extend(
                part.lower() for part in _CAMEL_BOUNDARY_RE.split(token) if part and part != token
            )
    return tokens


def _lexical_score_for_node(node: str, file_info, keywords: list[str]) -> float:
    """Score a file by lexical matches in its path and symbol metadata."""
    if not keywords:
        return 0.0

    score = 0.0
    matched_keywords = 0
    path_lower = node.lower()
    path_tokens = set(_tokenize(node))
    basename = node.rsplit("/", 1)[-1].lower()
    stem = _stem_from_path(node).lower()
    stem_tokens = _tokenize(stem)
    keyword_variants = {
        " ".join(keywords),
        "_".join(keywords),
        "-".join(keywords),
        "/".join(keywords),
    }
    compact_query = _compact_text("".join(keywords))
    compact_stem = _compact_text(stem)
    compact_path = _compact_text(node)

    if len(keywords) > 1:
        if compact_stem == compact_query:
            score += 28.0
        elif compact_query and compact_query in compact_stem:
            score += 18.0
        elif compact_query and compact_query in compact_path:
            score += 12.0

        if stem_tokens == keywords:
            score += 24.0
        elif _keywords_in_order(stem_tokens, keywords):
            score += 14.0

        for variant in keyword_variants:
            if variant and variant == stem:
                score += 26.0
                break
            if variant and variant in basename:
                score += 16.0
                break

    for kw in keywords:
        best_match = 0.0
        if kw == basename:
            best_match = max(best_match, 8.0)
        if kw == stem:
            best_match = max(best_match, 9.0)
        elif kw in basename:
            best_match = max(best_match, 5.0)
        if kw in path_tokens:
            best_match = max(best_match, 4.0)
        elif kw in path_lower:
            best_match = max(best_match, 2.5)

        if file_info is not None:
            for sym in getattr(file_info, "symbols", []):
                name_lower = sym.name.lower()
                signature_lower = sym.signature.lower()
                symbol_tokens = set(_tokenize(sym.name))
                symbol_token_list = _tokenize(sym.name)
                compact_symbol = _compact_text(sym.name)
                if kw == name_lower:
                    best_match = max(best_match, 12.0)
                elif kw in symbol_tokens:
                    best_match = max(best_match, 7.0)
                elif kw in name_lower:
                    best_match = max(best_match, 4.5)
                if kw in signature_lower:
                    best_match = max(best_match, 1.5)
                if len(keywords) > 1:
                    if compact_query and compact_symbol == compact_query:
                        best_match = max(best_match, 22.0)
                    elif compact_query and compact_query in compact_symbol:
                        best_match = max(best_match, 14.0)
                    if symbol_token_list == keywords:
                        best_match = max(best_match, 18.0)
                    elif _keywords_in_order(symbol_token_list, keywords):
                        best_match = max(best_match, 10.0)

        if best_match > 0:
            matched_keywords += 1
            score += best_match

    unique_keywords = len(set(keywords))
    if matched_keywords:
        score += matched_keywords * 1.5
        if unique_keywords > 1 and matched_keywords == unique_keywords:
            score += 6.0

    return score


def _expand_from_seeds(
    graph: nx.MultiDiGraph,
    seeds: dict[str, float],
    *,
    max_hops: int = 2,
    decay: float = 0.6,
) -> dict[str, float]:
    """Propagate seed relevance through nearby graph neighborhoods."""
    if not seeds:
        return {}

    expanded: dict[str, float] = dict(seeds)
    for seed, seed_score in seeds.items():
        queue: deque[tuple[str, int, float]] = deque([(seed, 0, float(seed_score))])
        seen: dict[str, int] = {seed: 0}

        while queue:
            node, hops, score = queue.popleft()
            if hops >= max_hops or score <= 0:
                continue

            neighbors = set(graph.successors(node)) | set(graph.predecessors(node))
            for neighbor in neighbors:
                next_hops = hops + 1
                if seen.get(neighbor, math.inf) < next_hops:
                    continue
                seen[neighbor] = next_hops
                propagated = score * decay
                if propagated <= 0:
                    continue
                expanded[neighbor] = max(expanded.get(neighbor, 0.0), propagated)
                queue.append((neighbor, next_hops, propagated))

    return expanded


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

    simple = _to_simple_digraph(graph)
    scores = _pagerank_power_iteration(simple, personalization=personalization, alpha=alpha)

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
    keywords = _tokenize(query)
    if not keywords:
        return None

    scores: dict[str, float] = {}
    for node in graph.nodes():
        data = graph.nodes[node]
        file_info = data.get("file_info")
        lexical = _lexical_score_for_node(node, file_info, keywords)
        if lexical > 0:
            scores[node] = lexical

    if not scores:
        return None

    # Build full personalization vector
    p: dict[str, float] = {n: 0.0 for n in graph.nodes()}
    p.update(scores)
    return p


def rank_for_query(
    graph: nx.MultiDiGraph,
    query: str,
) -> dict[str, float]:
    """Hybrid ranking for natural-language retrieval.

    Strong lexical matches should dominate the top of the ranking, while graph
    propagation helps bring in nearby dependencies and tests.
    """
    lexical = personalization_for_query(query, graph)
    if lexical is None:
        return rank_files(graph)

    keywords = set(_tokenize(query))
    lexical_norm = _normalize_scores(lexical)
    proximity_norm = _normalize_scores(_expand_from_seeds(graph, lexical_norm, max_hops=2))
    ppr_norm = _normalize_scores(rank_files(graph, personalization=lexical))

    combined = _combine_scores(
        (6.0, lexical_norm),
        (1.5, proximity_norm),
        (0.5, ppr_norm),
    )
    if not (keywords & _TEST_HINT_TOKENS):
        for node in list(combined.keys()):
            if _is_probable_test_path(node):
                combined[node] *= 0.6
    return dict(sorted(combined.items(), key=lambda item: item[1], reverse=True))


def rank_for_files(
    graph: nx.MultiDiGraph,
    files: list[str],
) -> dict[str, float]:
    """Hybrid ranking for file-seeded retrieval."""
    seed_map = personalization_for_files(files, graph)
    if seed_map is None:
        return rank_files(graph)

    seed_norm = _normalize_scores(seed_map)
    proximity_norm = _normalize_scores(_expand_from_seeds(graph, seed_norm, max_hops=2))
    ppr_norm = _normalize_scores(rank_files(graph, personalization=seed_map))

    combined = _combine_scores(
        (5.0, seed_norm),
        (2.5, proximity_norm),
        (1.0, ppr_norm),
    )
    return dict(sorted(combined.items(), key=lambda item: item[1], reverse=True))
