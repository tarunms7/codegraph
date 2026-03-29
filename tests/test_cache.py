"""Tests for codegraph.cache — SQLite persistent cache."""

from __future__ import annotations

import os
import threading
from unittest import mock

import pytest

from codegraph.cache import IndexCache
from codegraph.models import EdgeKind, FileInfo, Reference, Symbol, SymbolKind


@pytest.fixture()
def cache_dir(tmp_path):
    return str(tmp_path / "cache")


@pytest.fixture()
def cache(cache_dir):
    c = IndexCache(cache_dir)
    yield c
    c.close()


def _make_fileinfo(
    path: str = "src/auth.py",
    content_hash: str = "abc123",
    language: str = "python",
    lines: int = 50,
    symbols: list[Symbol] | None = None,
    references: list[Reference] | None = None,
) -> FileInfo:
    if symbols is None:
        symbols = [
            Symbol(
                name="authenticate",
                kind=SymbolKind.FUNCTION,
                file=path,
                line=10,
                signature="def authenticate(token: str) -> User",
                parent=None,
                end_line=25,
            ),
            Symbol(
                name="User",
                kind=SymbolKind.CLASS,
                file=path,
                line=1,
                signature="class User:",
                parent=None,
                end_line=8,
            ),
        ]
    if references is None:
        references = [
            Reference(
                source_file=path,
                target_name="models",
                target_file="src/models.py",
                line=1,
                kind=EdgeKind.IMPORTS,
            ),
        ]
    return FileInfo(
        path=path,
        language=language,
        content_hash=content_hash,
        symbols=symbols,
        references=references,
        lines=lines,
    )


class TestIndexCacheInit:
    def test_creates_directory(self, tmp_path):
        cache_dir = str(tmp_path / "new" / "nested" / "cache")
        c = IndexCache(cache_dir)
        assert os.path.isdir(cache_dir)
        assert os.path.isfile(os.path.join(cache_dir, "index.db"))
        c.close()

    def test_falls_back_on_permission_error(self, tmp_path):
        readonly_dir = str(tmp_path / "readonly" / ".codegraph")
        original_makedirs = os.makedirs

        def mock_makedirs(path, **kwargs):
            if path == readonly_dir:
                raise PermissionError("read-only filesystem")
            return original_makedirs(path, **kwargs)

        with mock.patch("codegraph.cache.os.makedirs", side_effect=mock_makedirs):
            c = IndexCache(readonly_dir)
            fi = _make_fileinfo()
            c.put(fi)
            result = c.get("src/auth.py", "abc123")
            assert result is not None
            c.close()

    def test_reopen_existing_db(self, cache_dir):
        c1 = IndexCache(cache_dir)
        fi = _make_fileinfo()
        c1.put(fi)
        c1.close()

        c2 = IndexCache(cache_dir)
        result = c2.get("src/auth.py", "abc123")
        assert result is not None
        assert result.path == "src/auth.py"
        c2.close()


class TestGet:
    def test_returns_none_when_empty(self, cache):
        assert cache.get("nonexistent.py", "hash") is None

    def test_returns_fileinfo_on_hash_match(self, cache):
        fi = _make_fileinfo()
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert result.path == fi.path
        assert result.language == fi.language
        assert result.content_hash == fi.content_hash
        assert result.lines == fi.lines

    def test_returns_none_on_hash_mismatch(self, cache):
        fi = _make_fileinfo()
        cache.put(fi)
        assert cache.get("src/auth.py", "different_hash") is None

    def test_deserializes_symbols(self, cache):
        fi = _make_fileinfo()
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert len(result.symbols) == 2
        sym = result.symbols[0]
        assert sym.name == "authenticate"
        assert sym.kind == SymbolKind.FUNCTION
        assert sym.file == "src/auth.py"
        assert sym.line == 10
        assert sym.signature == "def authenticate(token: str) -> User"
        assert sym.parent is None
        assert sym.end_line == 25

    def test_deserializes_references(self, cache):
        fi = _make_fileinfo()
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert len(result.references) == 1
        ref = result.references[0]
        assert ref.source_file == "src/auth.py"
        assert ref.target_name == "models"
        assert ref.target_file == "src/models.py"
        assert ref.line == 1
        assert ref.kind == EdgeKind.IMPORTS

    def test_empty_symbols_and_references(self, cache):
        fi = _make_fileinfo(symbols=[], references=[])
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert result.symbols == []
        assert result.references == []


class TestPut:
    def test_insert_new_entry(self, cache):
        fi = _make_fileinfo()
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None

    def test_replace_existing_entry(self, cache):
        fi1 = _make_fileinfo(content_hash="hash1", lines=50)
        cache.put(fi1)
        fi2 = _make_fileinfo(content_hash="hash2", lines=100)
        cache.put(fi2)
        assert cache.get("src/auth.py", "hash1") is None
        result = cache.get("src/auth.py", "hash2")
        assert result is not None
        assert result.lines == 100

    def test_all_symbol_kinds(self, cache):
        symbols = [
            Symbol(
                name=f"sym_{kind.value}",
                kind=kind,
                file="test.py",
                line=i,
                signature=f"{kind.value} sym",
            )
            for i, kind in enumerate(SymbolKind, start=1)
        ]
        fi = _make_fileinfo(symbols=symbols, references=[])
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert len(result.symbols) == len(SymbolKind)
        for sym, kind in zip(result.symbols, SymbolKind, strict=True):
            assert sym.kind == kind

    def test_all_edge_kinds(self, cache):
        refs = [
            Reference(source_file="a.py", target_name=f"t_{kind.value}", kind=kind)
            for kind in EdgeKind
        ]
        fi = _make_fileinfo(symbols=[], references=refs)
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert len(result.references) == len(EdgeKind)
        for ref, kind in zip(result.references, EdgeKind, strict=True):
            assert ref.kind == kind

    def test_symbol_with_parent(self, cache):
        sym = Symbol(
            name="do_thing",
            kind=SymbolKind.METHOD,
            file="a.py",
            line=5,
            signature="def do_thing(self)",
            parent="MyClass",
            end_line=10,
        )
        fi = _make_fileinfo(symbols=[sym], references=[])
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert result.symbols[0].parent == "MyClass"
        assert result.symbols[0].end_line == 10

    def test_reference_with_none_target(self, cache):
        ref = Reference(source_file="a.py", target_name="external_lib", target_file=None, line=3)
        fi = _make_fileinfo(symbols=[], references=[ref])
        cache.put(fi)
        result = cache.get("src/auth.py", "abc123")
        assert result is not None
        assert result.references[0].target_file is None


class TestInvalidate:
    def test_removes_entry(self, cache):
        fi = _make_fileinfo()
        cache.put(fi)
        cache.invalidate("src/auth.py")
        assert cache.get("src/auth.py", "abc123") is None

    def test_no_error_for_missing_path(self, cache):
        cache.invalidate("nonexistent.py")


class TestClear:
    def test_removes_all_entries(self, cache):
        cache.put(_make_fileinfo(path="a.py"))
        cache.put(_make_fileinfo(path="b.py"))
        cache.clear()
        assert cache.get_all() == {}

    def test_clear_empty_cache(self, cache):
        cache.clear()
        assert cache.get_all() == {}


class TestGetAll:
    def test_returns_empty_dict(self, cache):
        assert cache.get_all() == {}

    def test_returns_all_entries(self, cache):
        cache.put(_make_fileinfo(path="a.py"))
        cache.put(_make_fileinfo(path="b.py"))
        all_entries = cache.get_all()
        assert set(all_entries.keys()) == {"a.py", "b.py"}
        assert all_entries["a.py"].path == "a.py"
        assert all_entries["b.py"].path == "b.py"


class TestThreadSafety:
    def test_concurrent_puts(self, cache):
        errors = []

        def put_entries(start: int):
            try:
                for i in range(start, start + 20):
                    fi = _make_fileinfo(path=f"file_{i}.py", content_hash=f"hash_{i}")
                    cache.put(fi)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=put_entries, args=(i * 20,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        all_entries = cache.get_all()
        assert len(all_entries) == 100

    def test_concurrent_reads_and_writes(self, cache):
        for i in range(10):
            cache.put(_make_fileinfo(path=f"file_{i}.py", content_hash=f"hash_{i}"))

        errors = []

        def reader():
            try:
                for i in range(10):
                    cache.get(f"file_{i}.py", f"hash_{i}")
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(10, 20):
                    cache.put(_make_fileinfo(path=f"file_{i}.py", content_hash=f"hash_{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads += [threading.Thread(target=writer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


class TestCorruptedDb:
    def test_recreates_on_corruption(self, cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
        db_path = os.path.join(cache_dir, "index.db")
        with open(db_path, "w") as f:
            f.write("this is not a valid sqlite database")

        c = IndexCache(cache_dir)
        fi = _make_fileinfo()
        c.put(fi)
        result = c.get("src/auth.py", "abc123")
        assert result is not None
        c.close()


class TestPersistence:
    def test_survives_close_and_reopen(self, cache_dir):
        c1 = IndexCache(cache_dir)
        c1.put(_make_fileinfo())
        c1.close()

        c2 = IndexCache(cache_dir)
        result = c2.get("src/auth.py", "abc123")
        assert result is not None
        assert result.path == "src/auth.py"
        assert len(result.symbols) == 2
        assert len(result.references) == 1
        c2.close()
