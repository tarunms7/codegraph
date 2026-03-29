"""Token-budget-aware context rendering in markdown and JSON formats."""

from __future__ import annotations

import json
import logging
import math
from typing import Literal

import tiktoken

from codegraph.models import FileInfo, Symbol

logger = logging.getLogger("codegraph")

Format = Literal["markdown", "json"]

# Module-level cached encoding
_encoding: tiktoken.Encoding | None = None


def _get_encoding() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    return len(_get_encoding().encode(text))


def render_context(
    ranked_files: list[tuple[str, float]],
    file_infos: dict[str, FileInfo],
    token_budget: int,
    format: Format = "markdown",
) -> str:
    """Render context string fitting within token_budget.

    Files are partitioned into tiers:
    - Tier 1 (top 30%): full signatures
    - Tier 2 (next 30%): names only
    - Tier 3 (next 20%): path + summary
    - Tier 4 (bottom 20%): omitted
    """
    total_files = len(ranked_files)

    if token_budget <= 0:
        if format == "json":
            return json.dumps(
                {
                    "files": [],
                    "token_count": 0,
                    "token_budget": 0,
                    "files_included": 0,
                    "files_total": total_files,
                }
            )
        return ""

    # Partition into tiers
    t1_end = max(1, math.ceil(total_files * 0.3)) if total_files > 0 else 0
    t2_end = max(t1_end, math.ceil(total_files * 0.6)) if total_files > 0 else 0
    t3_end = max(t2_end, math.ceil(total_files * 0.8)) if total_files > 0 else 0

    tier1 = ranked_files[:t1_end]
    tier2 = ranked_files[t1_end:t2_end]
    tier3 = ranked_files[t2_end:t3_end]
    # tier4 = ranked_files[t3_end:]  # omitted

    if format == "json":
        return _render_json(tier1, tier2, tier3, file_infos, token_budget, total_files)
    return _render_markdown(tier1, tier2, tier3, file_infos, token_budget)


def _get_summary(fi: FileInfo) -> str | None:
    """Extract first docstring line or generate summary from symbol names."""
    # Look for a module-level docstring in the first symbol or content
    for sym in fi.symbols:
        if sym.kind.value in ("class", "module") and sym.signature:
            # Check if there's a docstring in the signature (unlikely, but check)
            pass

    # Generate summary from symbol names (C9 fallback)
    if fi.symbols:
        names = [s.name for s in fi.symbols[:5]]
        suffix = ", ..." if len(fi.symbols) > 5 else ""
        return f"Defines: {', '.join(names)}{suffix}"
    return None


def _render_markdown(
    tier1: list[tuple[str, float]],
    tier2: list[tuple[str, float]],
    tier3: list[tuple[str, float]],
    file_infos: dict[str, FileInfo],
    token_budget: int,
) -> str:
    """Render markdown output."""
    parts: list[str] = ["## Relevant Context\n"]
    current_tokens = count_tokens(parts[0])

    # Tier 1: full signatures
    for path, _rank in tier1:
        fi = file_infos.get(path)
        section = _render_tier1_md(path, fi)
        section_tokens = count_tokens(section)
        if current_tokens + section_tokens > token_budget:
            # Try with fewer symbols
            trimmed = _render_tier1_md_trimmed(path, fi, token_budget - current_tokens)
            if trimmed:
                parts.append(trimmed)
                current_tokens += count_tokens(trimmed)
            break
        parts.append(section)
        current_tokens += section_tokens

    # Tier 2: names only
    for path, _rank in tier2:
        fi = file_infos.get(path)
        section = _render_tier2_md(path, fi)
        section_tokens = count_tokens(section)
        if current_tokens + section_tokens > token_budget:
            break
        parts.append(section)
        current_tokens += section_tokens

    # Tier 3: path + summary as a single "Related files" block
    if tier3:
        related_header = "\n### Related files\n"
        header_tokens = count_tokens(related_header)
        if current_tokens + header_tokens <= token_budget:
            related_parts = [related_header]
            current_tokens += header_tokens
            for path, _rank in tier3:
                fi = file_infos.get(path)
                summary = _get_summary(fi) if fi else None
                line = f"- `{path}`"
                if summary:
                    line += f" — {summary}"
                line += "\n"
                line_tokens = count_tokens(line)
                if current_tokens + line_tokens > token_budget:
                    break
                related_parts.append(line)
                current_tokens += line_tokens
            if len(related_parts) > 1:
                parts.extend(related_parts)

    return "\n".join(parts) if len(parts) == 1 else "".join(parts)


def _render_tier1_md(path: str, fi: FileInfo | None) -> str:
    """Render a Tier 1 file section in markdown with full signatures."""
    lines = [f"\n### {path}\n"]
    summary = _get_summary(fi) if fi else None
    if summary:
        lines.append(f"> {summary}\n\n")
    else:
        lines.append("\n")

    if fi and fi.symbols:
        lang = fi.language if fi.language not in ("unknown", "binary") else ""
        lines.append(f"```{lang}\n")
        for sym in fi.symbols:
            lines.append(f"{sym.signature}\n")
        lines.append("```\n")

    return "".join(lines)


def _render_tier1_md_trimmed(path: str, fi: FileInfo | None, remaining_budget: int) -> str | None:
    """Render Tier 1 with progressively fewer symbols to fit budget."""
    if not fi or not fi.symbols:
        section = f"\n### {path}\n\n"
        return section if count_tokens(section) <= remaining_budget else None

    summary = _get_summary(fi)
    # Try with decreasing number of symbols
    for n in range(len(fi.symbols), 0, -1):
        lines = [f"\n### {path}\n"]
        if summary:
            lines.append(f"> {summary}\n\n")
        else:
            lines.append("\n")
        lang = fi.language if fi.language not in ("unknown", "binary") else ""
        lines.append(f"```{lang}\n")
        for sym in fi.symbols[:n]:
            lines.append(f"{sym.signature}\n")
        lines.append("```\n")
        section = "".join(lines)
        if count_tokens(section) <= remaining_budget:
            return section

    # Just the header
    section = f"\n### {path}\n\n"
    return section if count_tokens(section) <= remaining_budget else None


def _render_tier2_md(path: str, fi: FileInfo | None) -> str:
    """Render a Tier 2 file section with names only."""
    lines = [f"\n### {path}\n"]
    summary = _get_summary(fi) if fi else None
    if summary:
        lines.append(f"> {summary}\n\n")
    else:
        lines.append("\n")

    if fi and fi.symbols:
        for sym in fi.symbols:
            lines.append(f"- {sym.name}\n")

    return "".join(lines)


def _render_json(
    tier1: list[tuple[str, float]],
    tier2: list[tuple[str, float]],
    tier3: list[tuple[str, float]],
    file_infos: dict[str, FileInfo],
    token_budget: int,
    total_files: int,
) -> str:
    """Render JSON output per C23 strict schema."""
    entries: list[dict] = []

    def _sym_entry_full(sym: Symbol) -> dict:
        return {
            "name": sym.name,
            "kind": sym.kind.value,
            "signature": sym.signature,
            "line": sym.line,
            "parent": sym.parent,
        }

    def _sym_entry_name_only(sym: Symbol) -> dict:
        return {
            "name": sym.name,
            "kind": sym.kind.value,
            "signature": sym.name,
            "line": sym.line,
            "parent": sym.parent,
        }

    def _file_entry(path: str, rank: float, tier: int, symbols: list[dict]) -> dict:
        fi = file_infos.get(path)
        return {
            "path": path,
            "rank": rank,
            "tier": tier,
            "language": fi.language if fi else "unknown",
            "summary": _get_summary(fi) if fi else None,
            "symbols": symbols,
        }

    # Build all tier entries
    for path, rank in tier1:
        fi = file_infos.get(path)
        syms = [_sym_entry_full(s) for s in fi.symbols] if fi else []
        entries.append(_file_entry(path, rank, 1, syms))

    for path, rank in tier2:
        fi = file_infos.get(path)
        syms = [_sym_entry_name_only(s) for s in fi.symbols] if fi else []
        entries.append(_file_entry(path, rank, 2, syms))

    for path, rank in tier3:
        entries.append(_file_entry(path, rank, 3, []))

    # Progressively trim to fit token budget
    while entries:
        output = _build_json_output(entries, token_budget, total_files)
        if count_tokens(output) <= token_budget:
            return output
        # Remove last entry to fit
        entries.pop()

    # Empty output
    output = _build_json_output([], token_budget, total_files)
    return output


def _build_json_output(entries: list[dict], token_budget: int, total_files: int) -> str:
    """Build the final JSON string."""
    result = {
        "files": entries,
        "token_count": 0,  # placeholder
        "token_budget": token_budget,
        "files_included": len(entries),
        "files_total": total_files,
    }
    # Calculate actual token count
    text = json.dumps(result)
    result["token_count"] = count_tokens(text)
    # Re-serialize with correct token count
    return json.dumps(result)
