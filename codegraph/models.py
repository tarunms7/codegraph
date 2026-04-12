from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class SymbolKind(StrEnum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    TYPE = "type"
    INTERFACE = "interface"
    ENUM = "enum"
    CONSTANT = "constant"
    MODULE = "module"


class EdgeKind(StrEnum):
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    TESTS = "tests"
    USES_TYPE = "uses_type"


@dataclass(frozen=True, slots=True)
class Symbol:
    """A named code symbol extracted from a source file."""

    name: str
    kind: SymbolKind
    file: str
    line: int
    signature: str
    parent: str | None = None
    end_line: int | None = None


@dataclass(frozen=True, slots=True)
class Reference:
    """A reference from one file to a symbol in another file."""

    source_file: str
    target_name: str
    target_file: str | None = None
    line: int = 0
    kind: EdgeKind = EdgeKind.IMPORTS


@dataclass(slots=True)
class FileInfo:
    """Parsed metadata about a single source file."""

    path: str
    language: str
    content_hash: str
    symbols: list[Symbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    lines: int = 0


@dataclass(frozen=True, slots=True)
class EvidenceSymbol:
    """A symbol highlighted in a retrieval result."""

    name: str
    kind: SymbolKind
    line: int
    signature: str
    end_line: int | None = None
    score: float = 0.0
    matched_terms: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "line": self.line,
            "end_line": self.end_line,
            "signature": self.signature,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class EvidenceNeighbor:
    """A nearby file connected to the retrieved file in the code graph."""

    path: str
    kind: EdgeKind
    direction: Literal["incoming", "outgoing"]
    symbols: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind.value,
            "direction": self.direction,
            "symbols": list(self.symbols),
        }


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    """A ranked file result with focused symbols and retrieval reasons."""

    path: str
    rank: float
    language: str
    summary: str | None = None
    matched_terms: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    symbols: tuple[EvidenceSymbol, ...] = ()
    neighbors: tuple[EvidenceNeighbor, ...] = ()
    focus_range: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "rank": self.rank,
            "language": self.language,
            "summary": self.summary,
            "matched_terms": list(self.matched_terms),
            "reasons": list(self.reasons),
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "neighbors": [neighbor.to_dict() for neighbor in self.neighbors],
            "focus_range": list(self.focus_range) if self.focus_range is not None else None,
        }


@dataclass(frozen=True, slots=True)
class EvidencePack:
    """Structured retrieval output for query- or file-seeded context selection."""

    mode: Literal["query", "files"]
    confidence: float
    files: tuple[EvidenceFile, ...]
    query: str | None = None
    seed_files: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()
    missed_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "query": self.query,
            "seed_files": list(self.seed_files),
            "confidence": self.confidence,
            "matched_terms": list(self.matched_terms),
            "missed_terms": list(self.missed_terms),
            "files": [file.to_dict() for file in self.files],
        }
