"""Structured retrieval helpers built on top of codegraph ranking."""

from __future__ import annotations

from collections import defaultdict

import networkx as nx

from codegraph import ranker as ranker_mod
from codegraph.models import (
    EdgeKind,
    EvidenceFile,
    EvidenceNeighbor,
    EvidencePack,
    EvidenceSymbol,
    FileInfo,
    Symbol,
)

_DEFAULT_FILE_LIMIT = 8
_DEFAULT_SYMBOL_LIMIT = 5
_DEFAULT_NEIGHBOR_LIMIT = 3


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _get_summary(fi: FileInfo | None) -> str | None:
    """Generate a short navigational summary for a file."""
    if fi is None or not fi.symbols:
        return None
    names = [s.name for s in fi.symbols[:5]]
    suffix = ", ..." if len(fi.symbols) > 5 else ""
    return f"Defines: {', '.join(names)}{suffix}"


def _matched_terms_for_text(text: str, keywords: list[str]) -> tuple[str, ...]:
    lowered = text.lower()
    tokens = set(ranker_mod._tokenize(text))
    matched = [kw for kw in keywords if kw in lowered or kw in tokens]
    return tuple(dict.fromkeys(matched))


def _symbol_match_score(symbol: Symbol, keywords: list[str]) -> float:
    if not keywords:
        return 0.0

    name_lower = symbol.name.lower()
    signature_lower = symbol.signature.lower()
    name_tokens = ranker_mod._tokenize(symbol.name)
    name_token_set = set(name_tokens)
    compact_name = ranker_mod._compact_text(symbol.name)
    compact_query = ranker_mod._compact_text("".join(keywords))

    score = 0.0
    if len(keywords) > 1:
        if compact_query and compact_name == compact_query:
            score += 22.0
        elif compact_query and compact_query in compact_name:
            score += 12.0
        if name_tokens == keywords:
            score += 18.0
        elif ranker_mod._keywords_in_order(name_tokens, keywords):
            score += 10.0

    for keyword in keywords:
        if keyword == name_lower:
            score += 10.0
        elif keyword in name_token_set:
            score += 6.0
        elif keyword in name_lower:
            score += 4.0
        elif keyword in signature_lower:
            score += 1.0

    return score


def _focus_range(symbols: tuple[EvidenceSymbol, ...]) -> tuple[int, int] | None:
    if not symbols:
        return None
    start = min(symbol.line for symbol in symbols)
    end = max(symbol.end_line or symbol.line for symbol in symbols)
    return (start, end)


def _symbol_reasons(symbol: Symbol, matched_terms: tuple[str, ...], score: float) -> tuple[str, ...]:
    reasons: list[str] = []
    if matched_terms:
        reasons.append("query-term-match")
    if symbol.parent:
        reasons.append(f"member-of:{symbol.parent}")
    if score >= 18.0:
        reasons.append("exact-symbol-shape")
    elif score >= 8.0:
        reasons.append("strong-symbol-match")
    return tuple(reasons)


def _select_symbols(
    file_info: FileInfo,
    keywords: list[str],
    *,
    symbol_limit: int,
) -> tuple[EvidenceSymbol, ...]:
    candidates: list[EvidenceSymbol] = []
    for symbol in file_info.symbols:
        score = _symbol_match_score(symbol, keywords)
        matched_terms = _matched_terms_for_text(
            f"{symbol.name} {symbol.signature}",
            keywords,
        )
        if keywords and score <= 0 and not matched_terms:
            continue

        candidates.append(
            EvidenceSymbol(
                name=symbol.name,
                kind=symbol.kind,
                line=symbol.line,
                end_line=symbol.end_line,
                signature=symbol.signature,
                score=round(score, 4),
                matched_terms=matched_terms,
                reasons=_symbol_reasons(symbol, matched_terms, score),
            )
        )

    if not candidates:
        candidates = [
            EvidenceSymbol(
                name=symbol.name,
                kind=symbol.kind,
                line=symbol.line,
                end_line=symbol.end_line,
                signature=symbol.signature,
            )
            for symbol in file_info.symbols[:symbol_limit]
        ]

    ranked = sorted(
        candidates,
        key=lambda symbol: (-symbol.score, symbol.line, symbol.name.lower()),
    )
    return tuple(ranked[:symbol_limit])


def _neighbors_for_path(
    graph: nx.MultiDiGraph,
    path: str,
    *,
    neighbor_limit: int,
) -> tuple[EvidenceNeighbor, ...]:
    merged: dict[tuple[str, str, EdgeKind], set[str]] = defaultdict(set)

    for _src, target, data in graph.out_edges(path, data=True):
        kind = data.get("kind", EdgeKind.IMPORTS)
        if not isinstance(kind, EdgeKind):
            kind = EdgeKind(str(kind))
        merged[(target, "outgoing", kind)].update(data.get("symbols", []))

    for source, _tgt, data in graph.in_edges(path, data=True):
        kind = data.get("kind", EdgeKind.IMPORTS)
        if not isinstance(kind, EdgeKind):
            kind = EdgeKind(str(kind))
        merged[(source, "incoming", kind)].update(data.get("symbols", []))

    neighbors = [
        EvidenceNeighbor(
            path=neighbor_path,
            direction=direction,
            kind=kind,
            symbols=tuple(sorted(symbols)[:5]),
        )
        for (neighbor_path, direction, kind), symbols in merged.items()
    ]

    ranked = sorted(
        neighbors,
        key=lambda neighbor: (-len(neighbor.symbols), neighbor.path.lower(), neighbor.direction),
    )
    return tuple(ranked[:neighbor_limit])


def _file_reasons(
    path: str,
    file_info: FileInfo,
    keywords: list[str],
    *,
    seed_files: set[str],
    selected_symbols: tuple[EvidenceSymbol, ...],
    neighbors: tuple[EvidenceNeighbor, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    stem = ranker_mod._stem_from_path(path).lower()
    compact_query = ranker_mod._compact_text("".join(keywords))
    compact_stem = ranker_mod._compact_text(stem)
    path_matches = _matched_terms_for_text(path, keywords)
    symbol_matches = sorted(
        {term for symbol in selected_symbols for term in symbol.matched_terms},
    )

    if path in seed_files:
        reasons.append("seed-file")
    if compact_query and compact_stem == compact_query:
        reasons.append("exact-path-shape")
    elif len(keywords) > 1 and ranker_mod._keywords_in_order(ranker_mod._tokenize(stem), keywords):
        reasons.append("ordered-path-match")
    if path_matches:
        if len(path_matches) == len(set(keywords)):
            reasons.append("full-path-keyword-cover")
        reasons.append("path-match")
    if symbol_matches:
        reasons.append("symbol-match")
    if neighbors:
        reasons.append("graph-neighbor")
    if not reasons and file_info.symbols:
        reasons.append("structural-rank")
    return tuple(reasons)


def _matched_terms_for_file(
    path: str,
    symbols: tuple[EvidenceSymbol, ...],
    keywords: list[str],
) -> tuple[str, ...]:
    matched = set(_matched_terms_for_text(path, keywords))
    for symbol in symbols:
        matched.update(symbol.matched_terms)
    return tuple(sorted(matched))


def _build_file_evidence(
    graph: nx.MultiDiGraph,
    file_infos: dict[str, FileInfo],
    ranked_items: list[tuple[str, float]],
    keywords: list[str],
    *,
    limit: int,
    symbol_limit: int,
    neighbor_limit: int,
    seed_files: set[str],
) -> tuple[EvidenceFile, ...]:
    evidence_files: list[EvidenceFile] = []

    for path, rank in ranked_items:
        file_info = file_infos.get(path)
        if file_info is None:
            continue

        selected_symbols = _select_symbols(file_info, keywords, symbol_limit=symbol_limit)
        neighbors = _neighbors_for_path(graph, path, neighbor_limit=neighbor_limit)
        matched_terms = _matched_terms_for_file(path, selected_symbols, keywords)
        evidence_files.append(
            EvidenceFile(
                path=path,
                rank=round(rank, 6),
                language=file_info.language,
                summary=_get_summary(file_info),
                matched_terms=matched_terms,
                reasons=_file_reasons(
                    path,
                    file_info,
                    keywords,
                    seed_files=seed_files,
                    selected_symbols=selected_symbols,
                    neighbors=neighbors,
                ),
                symbols=selected_symbols,
                neighbors=neighbors,
                focus_range=_focus_range(selected_symbols),
            )
        )
        if len(evidence_files) >= limit:
            break

    return tuple(evidence_files)


def _confidence_for_query(keywords: list[str], files: tuple[EvidenceFile, ...]) -> float:
    if not files:
        return 0.0

    keyword_set = set(keywords)
    covered_terms = {term for file in files[:3] for term in file.matched_terms}
    coverage = (len(covered_terms) / len(keyword_set)) if keyword_set else 1.0

    top_rank = files[0].rank
    second_rank = files[1].rank if len(files) > 1 else 0.0
    if second_rank <= 0:
        margin_score = 1.0
    else:
        margin_score = _clamp((top_rank / second_rank - 1.0) / 1.5)

    exact_bonus = 1.0 if any("exact-path-shape" == reason for reason in files[0].reasons) else 0.0
    reason_bonus = 1.0 if "symbol-match" in files[0].reasons else 0.0

    confidence = 0.2 + (0.35 * coverage) + (0.25 * margin_score) + (0.1 * exact_bonus)
    confidence += 0.1 * reason_bonus
    return round(_clamp(confidence), 3)


def _confidence_for_files(seed_files: set[str], files: tuple[EvidenceFile, ...]) -> float:
    if not files:
        return 0.0

    ranked_paths = {file.path for file in files}
    seed_coverage = (len(seed_files & ranked_paths) / len(seed_files)) if seed_files else 1.0
    neighbor_bonus = _clamp(sum(1 for file in files[:3] if file.neighbors) / 3.0)
    focus_bonus = _clamp(sum(1 for file in files[:3] if file.focus_range) / 3.0)

    confidence = 0.45 + (0.35 * seed_coverage) + (0.1 * neighbor_bonus) + (0.1 * focus_bonus)
    return round(_clamp(confidence), 3)


def build_evidence_for_query(
    graph: nx.MultiDiGraph,
    file_infos: dict[str, FileInfo],
    query: str,
    *,
    limit: int = _DEFAULT_FILE_LIMIT,
    symbol_limit: int = _DEFAULT_SYMBOL_LIMIT,
    neighbor_limit: int = _DEFAULT_NEIGHBOR_LIMIT,
) -> EvidencePack:
    keywords = ranker_mod._tokenize(query)
    if not keywords:
        return EvidencePack(
            mode="query",
            query=query,
            confidence=0.0,
            files=(),
        )

    ranked_items = list(ranker_mod.rank_for_query(graph, query).items())
    files = _build_file_evidence(
        graph,
        file_infos,
        ranked_items,
        keywords,
        limit=limit,
        symbol_limit=symbol_limit,
        neighbor_limit=neighbor_limit,
        seed_files=set(),
    )

    matched_terms = tuple(sorted({term for file in files for term in file.matched_terms}))
    missed_terms = tuple(term for term in dict.fromkeys(keywords) if term not in matched_terms)
    return EvidencePack(
        mode="query",
        query=query,
        confidence=_confidence_for_query(keywords, files),
        files=files,
        matched_terms=matched_terms,
        missed_terms=missed_terms,
    )


def build_evidence_for_files(
    graph: nx.MultiDiGraph,
    file_infos: dict[str, FileInfo],
    files: list[str],
    *,
    limit: int = _DEFAULT_FILE_LIMIT,
    symbol_limit: int = _DEFAULT_SYMBOL_LIMIT,
    neighbor_limit: int = _DEFAULT_NEIGHBOR_LIMIT,
) -> EvidencePack:
    seed_files = [path for path in files if path in file_infos]
    if not seed_files:
        return EvidencePack(
            mode="files",
            confidence=0.0,
            files=(),
            seed_files=(),
        )

    ranked_items = list(ranker_mod.rank_for_files(graph, seed_files).items())
    evidence_files = _build_file_evidence(
        graph,
        file_infos,
        ranked_items,
        [],
        limit=limit,
        symbol_limit=symbol_limit,
        neighbor_limit=neighbor_limit,
        seed_files=set(seed_files),
    )

    return EvidencePack(
        mode="files",
        confidence=_confidence_for_files(set(seed_files), evidence_files),
        files=evidence_files,
        seed_files=tuple(seed_files),
    )
