from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


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
