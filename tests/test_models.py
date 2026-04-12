"""Tests for codegraph.models — data models, enums, and dataclass contracts."""

from __future__ import annotations

import copy

import pytest

from codegraph.models import (
    EdgeKind,
    EvidenceFile,
    EvidenceNeighbor,
    EvidencePack,
    EvidenceSymbol,
    FileInfo,
    Reference,
    Symbol,
    SymbolKind,
)

# ---------------------------------------------------------------------------
# SymbolKind
# ---------------------------------------------------------------------------


class TestSymbolKind:
    def test_values(self):
        assert SymbolKind.CLASS == "class"
        assert SymbolKind.FUNCTION == "function"
        assert SymbolKind.METHOD == "method"
        assert SymbolKind.VARIABLE == "variable"
        assert SymbolKind.TYPE == "type"
        assert SymbolKind.INTERFACE == "interface"
        assert SymbolKind.ENUM == "enum"
        assert SymbolKind.CONSTANT == "constant"
        assert SymbolKind.MODULE == "module"

    def test_member_count(self):
        assert len(SymbolKind) == 9

    def test_is_str(self):
        assert isinstance(SymbolKind.CLASS, str)

    def test_from_value(self):
        assert SymbolKind("class") is SymbolKind.CLASS


# ---------------------------------------------------------------------------
# EdgeKind
# ---------------------------------------------------------------------------


class TestEdgeKind:
    def test_values(self):
        assert EdgeKind.IMPORTS == "imports"
        assert EdgeKind.CALLS == "calls"
        assert EdgeKind.INHERITS == "inherits"
        assert EdgeKind.IMPLEMENTS == "implements"
        assert EdgeKind.TESTS == "tests"
        assert EdgeKind.USES_TYPE == "uses_type"

    def test_member_count(self):
        assert len(EdgeKind) == 6

    def test_is_str(self):
        assert isinstance(EdgeKind.IMPORTS, str)


# ---------------------------------------------------------------------------
# Symbol
# ---------------------------------------------------------------------------


class TestSymbol:
    def test_create(self):
        s = Symbol(
            name="authenticate",
            kind=SymbolKind.FUNCTION,
            file="auth.py",
            line=10,
            signature="def authenticate(token: str) -> User",
        )
        assert s.name == "authenticate"
        assert s.kind is SymbolKind.FUNCTION
        assert s.file == "auth.py"
        assert s.line == 10
        assert s.signature == "def authenticate(token: str) -> User"
        assert s.parent is None
        assert s.end_line is None

    def test_with_optional_fields(self):
        s = Symbol(
            name="do_stuff",
            kind=SymbolKind.METHOD,
            file="service.py",
            line=20,
            signature="def do_stuff(self) -> None",
            parent="Service",
            end_line=35,
        )
        assert s.parent == "Service"
        assert s.end_line == 35

    def test_frozen(self):
        s = Symbol(name="x", kind=SymbolKind.VARIABLE, file="a.py", line=1, signature="x = 1")
        with pytest.raises(AttributeError):
            s.name = "y"  # type: ignore[misc]

    def test_slots(self):
        s = Symbol(name="x", kind=SymbolKind.VARIABLE, file="a.py", line=1, signature="x = 1")
        assert hasattr(s, "__slots__")
        with pytest.raises((AttributeError, TypeError)):
            s.nonexistent = 42  # type: ignore[attr-defined]

    def test_equality(self):
        args = dict(name="f", kind=SymbolKind.FUNCTION, file="a.py", line=1, signature="def f()")
        assert Symbol(**args) == Symbol(**args)

    def test_hashable(self):
        s = Symbol(name="f", kind=SymbolKind.FUNCTION, file="a.py", line=1, signature="def f()")
        assert hash(s) == hash(s)
        s_set = {s}
        assert s in s_set


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------


class TestReference:
    def test_create_minimal(self):
        r = Reference(source_file="main.py", target_name="auth")
        assert r.source_file == "main.py"
        assert r.target_name == "auth"
        assert r.target_file is None
        assert r.line == 0
        assert r.kind is EdgeKind.IMPORTS

    def test_create_full(self):
        r = Reference(
            source_file="main.py",
            target_name="User",
            target_file="models.py",
            line=5,
            kind=EdgeKind.INHERITS,
        )
        assert r.target_file == "models.py"
        assert r.line == 5
        assert r.kind is EdgeKind.INHERITS

    def test_frozen(self):
        r = Reference(source_file="a.py", target_name="b")
        with pytest.raises(AttributeError):
            r.source_file = "c.py"  # type: ignore[misc]

    def test_hashable(self):
        r = Reference(source_file="a.py", target_name="b")
        r_set = {r}
        assert r in r_set


# ---------------------------------------------------------------------------
# FileInfo
# ---------------------------------------------------------------------------


class TestFileInfo:
    def test_create_minimal(self):
        fi = FileInfo(path="app.py", language="python", content_hash="abc123")
        assert fi.path == "app.py"
        assert fi.language == "python"
        assert fi.content_hash == "abc123"
        assert fi.symbols == []
        assert fi.references == []
        assert fi.lines == 0

    def test_mutable(self):
        fi = FileInfo(path="app.py", language="python", content_hash="abc123")
        sym = Symbol(
            name="main", kind=SymbolKind.FUNCTION, file="app.py", line=1, signature="def main()"
        )
        fi.symbols.append(sym)
        assert len(fi.symbols) == 1

        fi.lines = 42
        assert fi.lines == 42

    def test_slots(self):
        fi = FileInfo(path="app.py", language="python", content_hash="abc123")
        assert hasattr(fi, "__slots__")
        with pytest.raises(AttributeError):
            fi.extra = "nope"  # type: ignore[attr-defined]

    def test_default_factory_independence(self):
        fi1 = FileInfo(path="a.py", language="python", content_hash="h1")
        fi2 = FileInfo(path="b.py", language="python", content_hash="h2")
        fi1.symbols.append(
            Symbol(name="x", kind=SymbolKind.VARIABLE, file="a.py", line=1, signature="x = 1")
        )
        assert fi2.symbols == []

    def test_not_frozen(self):
        fi = FileInfo(path="a.py", language="python", content_hash="h")
        fi.path = "b.py"
        assert fi.path == "b.py"

    def test_copy(self):
        fi = FileInfo(path="a.py", language="python", content_hash="h", lines=10)
        fi2 = copy.copy(fi)
        assert fi2.path == fi.path
        assert fi2.lines == fi.lines


# ---------------------------------------------------------------------------
# Evidence models
# ---------------------------------------------------------------------------


class TestEvidenceModels:
    def test_evidence_symbol_to_dict(self):
        symbol = EvidenceSymbol(
            name="authenticate",
            kind=SymbolKind.FUNCTION,
            line=12,
            end_line=16,
            signature="def authenticate(token: str) -> User",
            score=19.5,
            matched_terms=("authenticate", "token"),
            reasons=("query-term-match", "strong-symbol-match"),
        )
        data = symbol.to_dict()
        assert data["kind"] == "function"
        assert data["end_line"] == 16
        assert data["matched_terms"] == ["authenticate", "token"]

    def test_evidence_file_to_dict(self):
        file_result = EvidenceFile(
            path="auth.py",
            rank=0.92,
            language="python",
            summary="Defines: authenticate",
            matched_terms=("authenticate",),
            reasons=("path-match", "symbol-match"),
            symbols=(
                EvidenceSymbol(
                    name="authenticate",
                    kind=SymbolKind.FUNCTION,
                    line=10,
                    signature="def authenticate()",
                ),
            ),
            neighbors=(
                EvidenceNeighbor(
                    path="models.py",
                    kind=EdgeKind.IMPORTS,
                    direction="outgoing",
                    symbols=("User",),
                ),
            ),
            focus_range=(10, 10),
        )
        data = file_result.to_dict()
        assert data["focus_range"] == [10, 10]
        assert data["neighbors"][0]["kind"] == "imports"
        assert data["symbols"][0]["name"] == "authenticate"

    def test_evidence_pack_to_dict(self):
        pack = EvidencePack(
            mode="query",
            query="authenticate token",
            confidence=0.91,
            files=(),
            matched_terms=("authenticate",),
            missed_terms=("token",),
        )
        data = pack.to_dict()
        assert data["mode"] == "query"
        assert data["confidence"] == 0.91
        assert data["missed_terms"] == ["token"]
