"""Tests for codegraph.parser module."""

from __future__ import annotations

import hashlib
import os
import tempfile

from codegraph.models import EdgeKind, FileInfo, Reference, Symbol, SymbolKind
from codegraph.parser import (
    _clean_import_text,
    parse_file,
    parse_files,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PY_PROJECT = os.path.join(FIXTURES, "python_project")
TS_PROJECT = os.path.join(FIXTURES, "typescript_project")
MIXED_PROJECT = os.path.join(FIXTURES, "mixed_project")


# ---------------------------------------------------------------------------
# parse_file — Python
# ---------------------------------------------------------------------------


class TestParseFilePython:
    def test_python_functions(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        assert info.language == "python"
        names = {s.name for s in info.symbols if s.kind == SymbolKind.FUNCTION}
        assert "authenticate" in names
        assert "authorize" in names

    def test_python_class(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        classes = [s for s in info.symbols if s.kind == SymbolKind.CLASS]
        assert len(classes) == 1
        assert classes[0].name == "AuthHandler"

    def test_python_methods(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        methods = [s for s in info.symbols if s.kind == SymbolKind.METHOD]
        assert {m.name for m in methods} == {"login", "logout"}
        for m in methods:
            assert m.parent == "AuthHandler"

    def test_python_no_duplicate_method_as_function(self):
        """Methods should not also appear as functions."""
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        funcs = [s for s in info.symbols if s.kind == SymbolKind.FUNCTION]
        func_names = {f.name for f in funcs}
        assert "login" not in func_names
        assert "logout" not in func_names

    def test_python_inheritance_reference(self):
        info = parse_file(os.path.join(PY_PROJECT, "models.py"), PY_PROJECT)
        inherits = [r for r in info.references if r.kind == EdgeKind.INHERITS]
        assert len(inherits) == 1
        assert inherits[0].target_name == "User"

    def test_python_relative_import(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        imports = [r for r in info.references if r.kind == EdgeKind.IMPORTS]
        assert len(imports) == 1
        assert imports[0].target_name == ".models"

    def test_python_dotted_import(self):
        """Test absolute dotted import extraction."""
        code = b"import os.path\nfrom collections.abc import Mapping\n"
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            try:
                info = parse_file(f.name, tempfile.gettempdir())
                imports = [r for r in info.references if r.kind == EdgeKind.IMPORTS]
                targets = {r.target_name for r in imports}
                assert "os.path" in targets
                assert "collections.abc" in targets
            finally:
                os.unlink(f.name)

    def test_python_signature_extraction(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        auth_fn = next(s for s in info.symbols if s.name == "authenticate")
        assert auth_fn.signature == "def authenticate(token: str) -> User"

    def test_python_line_numbers(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        # Line numbers are 1-indexed
        auth_fn = next(s for s in info.symbols if s.name == "authenticate")
        assert auth_fn.line >= 1

    def test_python_end_line(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        auth_fn = next(s for s in info.symbols if s.name == "authenticate")
        assert auth_fn.end_line is not None
        assert auth_fn.end_line >= auth_fn.line

    def test_python_content_hash(self):
        fp = os.path.join(PY_PROJECT, "auth.py")
        info = parse_file(fp, PY_PROJECT)
        with open(fp, "rb") as f:
            expected = hashlib.sha256(f.read()).hexdigest()
        assert info.content_hash == expected

    def test_python_line_count(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        assert info.lines > 0

    def test_python_relative_path(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        assert info.path == "auth.py"

    def test_python_variables(self):
        """Top-level variable assignments should be captured."""
        info = parse_file(os.path.join(PY_PROJECT, "app.py"), PY_PROJECT)
        variables = [s for s in info.symbols if s.kind == SymbolKind.VARIABLE]
        # app.py has VERSION top-level assignment
        assert any(v.name == "VERSION" for v in variables)


# ---------------------------------------------------------------------------
# parse_file — TypeScript
# ---------------------------------------------------------------------------


class TestParseFileTypeScript:
    def test_ts_class(self):
        info = parse_file(os.path.join(TS_PROJECT, "auth.ts"), TS_PROJECT)
        classes = [s for s in info.symbols if s.kind == SymbolKind.CLASS]
        assert any(c.name == "AuthService" for c in classes)

    def test_ts_methods(self):
        info = parse_file(os.path.join(TS_PROJECT, "auth.ts"), TS_PROJECT)
        methods = [s for s in info.symbols if s.kind == SymbolKind.METHOD]
        method_names = {m.name for m in methods}
        assert "authenticate" in method_names
        assert "authorize" in method_names

    def test_ts_function(self):
        info = parse_file(os.path.join(TS_PROJECT, "auth.ts"), TS_PROJECT)
        funcs = [s for s in info.symbols if s.kind == SymbolKind.FUNCTION]
        assert any(f.name == "createToken" for f in funcs)

    def test_ts_import_strips_quotes(self):
        info = parse_file(os.path.join(TS_PROJECT, "auth.ts"), TS_PROJECT)
        imports = [r for r in info.references if r.kind == EdgeKind.IMPORTS]
        for imp in imports:
            assert not imp.target_name.startswith("'")
            assert not imp.target_name.startswith('"')

    def test_ts_import_target(self):
        info = parse_file(os.path.join(TS_PROJECT, "auth.ts"), TS_PROJECT)
        imports = [r for r in info.references if r.kind == EdgeKind.IMPORTS]
        targets = {r.target_name for r in imports}
        assert "./types" in targets

    def test_ts_interfaces(self):
        info = parse_file(os.path.join(TS_PROJECT, "types.ts"), TS_PROJECT)
        interfaces = [s for s in info.symbols if s.kind == SymbolKind.INTERFACE]
        iface_names = {i.name for i in interfaces}
        assert len(iface_names) > 0

    def test_ts_method_parent(self):
        info = parse_file(os.path.join(TS_PROJECT, "auth.ts"), TS_PROJECT)
        methods = [s for s in info.symbols if s.kind == SymbolKind.METHOD]
        for m in methods:
            assert m.parent == "AuthService"


# ---------------------------------------------------------------------------
# parse_file — binary / unknown / edge cases
# ---------------------------------------------------------------------------


class TestParseFileEdgeCases:
    def test_binary_file(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00\x01\x02binary content")
            f.flush()
            try:
                info = parse_file(f.name, tempfile.gettempdir())
                assert info.language == "binary"
                assert info.symbols == []
                assert info.references == []
            finally:
                os.unlink(f.name)

    def test_unknown_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"some text content")
            f.flush()
            try:
                info = parse_file(f.name, tempfile.gettempdir())
                assert info.language == "unknown"
                assert info.symbols == []
            finally:
                os.unlink(f.name)

    def test_nonexistent_file(self):
        info = parse_file("/nonexistent/path/file.py", "/nonexistent/path")
        assert info.language == "unknown"
        assert info.content_hash == ""

    def test_empty_python_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"")
            f.flush()
            try:
                info = parse_file(f.name, tempfile.gettempdir())
                assert info.language == "python"
                assert info.symbols == []
                assert info.lines == 0
            finally:
                os.unlink(f.name)

    def test_syntax_error_partial_parse(self):
        """Tree-sitter is error-tolerant — should still extract valid symbols."""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"def good_function():\n    pass\n\ndef bad_function(\n")
            f.flush()
            try:
                info = parse_file(f.name, tempfile.gettempdir())
                assert info.language == "python"
                # Should extract at least the good function
                names = {s.name for s in info.symbols}
                assert "good_function" in names
            finally:
                os.unlink(f.name)

    def test_signature_truncation(self):
        """Signatures longer than 200 chars should be truncated."""
        long_params = ", ".join(f"param{i}: str" for i in range(30))
        code = f"def very_long_function({long_params}):\n    pass\n".encode()
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            try:
                info = parse_file(f.name, tempfile.gettempdir())
                fn = next(s for s in info.symbols if s.name == "very_long_function")
                assert len(fn.signature) <= 200
                assert fn.signature.endswith("...")
            finally:
                os.unlink(f.name)

    def test_unicode_content(self):
        code = 'def grüße():\n    """Héllo wörld."""\n    pass\n'.encode()
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            try:
                info = parse_file(f.name, tempfile.gettempdir())
                assert info.language == "python"
                names = {s.name for s in info.symbols}
                assert "grüße" in names
            finally:
                os.unlink(f.name)


# ---------------------------------------------------------------------------
# parse_files — parallel parsing
# ---------------------------------------------------------------------------


class TestParseFiles:
    def test_parse_multiple_files(self):
        files = [
            os.path.join(PY_PROJECT, "auth.py"),
            os.path.join(PY_PROJECT, "models.py"),
        ]
        results = parse_files(files, PY_PROJECT)
        assert "auth.py" in results
        assert "models.py" in results
        assert results["auth.py"].language == "python"
        assert results["models.py"].language == "python"

    def test_parse_files_empty_list(self):
        results = parse_files([], PY_PROJECT)
        assert results == {}

    def test_parse_files_mixed_languages(self):
        files = [
            os.path.join(MIXED_PROJECT, "backend", "main.py"),
            os.path.join(MIXED_PROJECT, "frontend", "api.ts"),
        ]
        results = parse_files(files, MIXED_PROJECT)
        assert len(results) == 2
        langs = {info.language for info in results.values()}
        assert "python" in langs
        assert "typescript" in langs

    def test_parse_files_with_bad_file(self):
        """Bad files should be skipped, good files still parsed."""
        files = [
            os.path.join(PY_PROJECT, "auth.py"),
            "/nonexistent/file.py",
        ]
        results = parse_files(files, PY_PROJECT)
        assert "auth.py" in results
        assert len(results) >= 1  # at least the good file


# ---------------------------------------------------------------------------
# _clean_import_text helper
# ---------------------------------------------------------------------------


class TestCleanImportText:
    def test_strip_double_quotes(self):
        assert _clean_import_text('"some/path"', "go") == "some/path"

    def test_strip_single_quotes(self):
        assert _clean_import_text("'./auth'", "typescript") == "./auth"

    def test_no_quotes(self):
        assert _clean_import_text("os.path", "python") == "os.path"

    def test_empty_string(self):
        assert _clean_import_text("", "python") == ""


# ---------------------------------------------------------------------------
# FileInfo contract checks
# ---------------------------------------------------------------------------


class TestFileInfoContract:
    def test_fileinfo_fields(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        assert isinstance(info, FileInfo)
        assert isinstance(info.path, str)
        assert isinstance(info.language, str)
        assert isinstance(info.content_hash, str)
        assert isinstance(info.symbols, list)
        assert isinstance(info.references, list)
        assert isinstance(info.lines, int)

    def test_symbol_fields(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        for s in info.symbols:
            assert isinstance(s, Symbol)
            assert isinstance(s.name, str)
            assert isinstance(s.kind, SymbolKind)
            assert isinstance(s.file, str)
            assert isinstance(s.line, int)
            assert isinstance(s.signature, str)

    def test_reference_fields(self):
        info = parse_file(os.path.join(PY_PROJECT, "auth.py"), PY_PROJECT)
        for r in info.references:
            assert isinstance(r, Reference)
            assert isinstance(r.source_file, str)
            assert isinstance(r.target_name, str)
            assert isinstance(r.line, int)
            assert isinstance(r.kind, EdgeKind)

    def test_never_raises(self):
        """parse_file should never raise — always returns FileInfo."""
        # Nonexistent file
        info = parse_file("/bad/path.py", "/bad")
        assert isinstance(info, FileInfo)

        # Binary-ish path
        info2 = parse_file("/dev/null", "/dev")
        assert isinstance(info2, FileInfo)
