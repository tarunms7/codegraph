"""Tests for codegraph.graph — dependency graph builder."""

from __future__ import annotations

import networkx as nx

from codegraph.graph import _detect_test_edges, _normalize_path, build_graph, resolve_references
from codegraph.models import EdgeKind, FileInfo, Reference, Symbol, SymbolKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_symbol(name: str, kind: SymbolKind, file: str, line: int = 1, sig: str = "") -> Symbol:
    return Symbol(name=name, kind=kind, file=file, line=line, signature=sig or f"def {name}()")


def _make_fi(
    path: str,
    language: str = "python",
    symbols: list[Symbol] | None = None,
    refs: list[Reference] | None = None,
) -> FileInfo:
    return FileInfo(
        path=path,
        language=language,
        content_hash="abc123",
        symbols=symbols or [],
        references=refs or [],
        lines=10,
    )


# ---------------------------------------------------------------------------
# Python fixture edges (from contract)
# ---------------------------------------------------------------------------


def _python_fixture_files() -> dict[str, FileInfo]:
    """Build FileInfo dicts matching tests/fixtures/python_project/ contract."""
    models = _make_fi(
        "models.py",
        symbols=[
            _make_symbol("User", SymbolKind.CLASS, "models.py", 4, "class User"),
            _make_symbol("Admin", SymbolKind.CLASS, "models.py", 15, "class Admin(User)"),
        ],
    )
    auth = _make_fi(
        "auth.py",
        symbols=[
            _make_symbol(
                "authenticate",
                SymbolKind.FUNCTION,
                "auth.py",
                6,
                "def authenticate(token: str) -> User",
            ),
            _make_symbol(
                "authorize",
                SymbolKind.FUNCTION,
                "auth.py",
                10,
                "def authorize(user: User, permission: str) -> bool",
            ),
            _make_symbol("AuthHandler", SymbolKind.CLASS, "auth.py", 14, "class AuthHandler"),
        ],
        refs=[
            Reference(source_file="auth.py", target_name=".models", kind=EdgeKind.IMPORTS),
        ],
    )
    app = _make_fi(
        "app.py",
        symbols=[
            _make_symbol("VERSION", SymbolKind.CONSTANT, "app.py", 4, 'VERSION = "1.0.0"'),
            _make_symbol("Application", SymbolKind.CLASS, "app.py", 7, "class Application"),
            _make_symbol(
                "create_app",
                SymbolKind.FUNCTION,
                "app.py",
                12,
                "def create_app(config: dict) -> Application",
            ),
        ],
        refs=[
            Reference(source_file="app.py", target_name=".auth", kind=EdgeKind.IMPORTS),
            Reference(source_file="app.py", target_name=".models", kind=EdgeKind.IMPORTS),
        ],
    )
    test_auth = _make_fi(
        "tests/test_auth.py",
        symbols=[
            _make_symbol("test_authenticate", SymbolKind.FUNCTION, "tests/test_auth.py", 6),
            _make_symbol("test_authorize", SymbolKind.FUNCTION, "tests/test_auth.py", 11),
        ],
        refs=[
            Reference(
                source_file="tests/test_auth.py", target_name="..auth", kind=EdgeKind.IMPORTS
            ),
        ],
    )
    return {
        "models.py": models,
        "auth.py": auth,
        "app.py": app,
        "tests/test_auth.py": test_auth,
    }


# ---------------------------------------------------------------------------
# TypeScript fixture edges (from contract)
# ---------------------------------------------------------------------------


def _ts_fixture_files() -> dict[str, FileInfo]:
    """Build FileInfo dicts matching tests/fixtures/typescript_project/ contract."""
    types_ts = _make_fi(
        "types.ts",
        language="typescript",
        symbols=[
            _make_symbol("IUser", SymbolKind.INTERFACE, "types.ts", 1, "export interface IUser"),
            _make_symbol(
                "IAuthConfig", SymbolKind.INTERFACE, "types.ts", 6, "export interface IAuthConfig"
            ),
            _make_symbol(
                "Role",
                SymbolKind.TYPE,
                "types.ts",
                11,
                "export type Role = 'admin' | 'user' | 'guest'",
            ),
            _make_symbol("Permission", SymbolKind.ENUM, "types.ts", 13, "export enum Permission"),
        ],
    )
    auth_ts = _make_fi(
        "auth.ts",
        language="typescript",
        symbols=[
            _make_symbol("AuthService", SymbolKind.CLASS, "auth.ts", 3, "export class AuthService"),
            _make_symbol(
                "createToken",
                SymbolKind.FUNCTION,
                "auth.ts",
                21,
                "export function createToken(user: IUser): string",
            ),
        ],
        refs=[
            Reference(source_file="auth.ts", target_name="./types", kind=EdgeKind.IMPORTS),
        ],
    )
    index_ts = _make_fi(
        "index.ts",
        language="typescript",
        symbols=[
            _make_symbol("App", SymbolKind.CLASS, "index.ts", 4, "export class App"),
        ],
        refs=[
            Reference(source_file="index.ts", target_name="./auth", kind=EdgeKind.IMPORTS),
            Reference(source_file="index.ts", target_name="./types", kind=EdgeKind.IMPORTS),
        ],
    )
    test_auth = _make_fi(
        "__tests__/auth.test.ts",
        language="typescript",
        symbols=[],
        refs=[
            Reference(
                source_file="__tests__/auth.test.ts", target_name="../auth", kind=EdgeKind.IMPORTS
            ),
        ],
    )
    return {
        "types.ts": types_ts,
        "auth.ts": auth_ts,
        "index.ts": index_ts,
        "__tests__/auth.test.ts": test_auth,
    }


# ===================================================================
# build_graph
# ===================================================================


class TestBuildGraph:
    def test_returns_multidigraph(self):
        files = _python_fixture_files()
        g = build_graph(files)
        assert isinstance(g, nx.MultiDiGraph)

    def test_nodes_have_file_info(self):
        files = _python_fixture_files()
        g = build_graph(files)
        for path in files:
            assert g.has_node(path)
            assert g.nodes[path]["file_info"] is files[path]

    def test_no_self_loops(self):
        files = _python_fixture_files()
        g = build_graph(files)
        for u, v in g.edges():
            assert u != v, f"Self-loop found: {u} → {v}"

    def test_empty_input(self):
        g = build_graph({})
        assert g.number_of_nodes() == 0
        assert g.number_of_edges() == 0

    def test_python_fixture_edges(self):
        """Verify edges per PythonFixtureEdges contract."""
        files = _python_fixture_files()
        g = build_graph(files)

        # auth.py -> models.py : IMPORTS
        assert _has_edge_kind(g, "auth.py", "models.py", EdgeKind.IMPORTS)

        # app.py -> auth.py : IMPORTS
        assert _has_edge_kind(g, "app.py", "auth.py", EdgeKind.IMPORTS)

        # app.py -> models.py : IMPORTS
        assert _has_edge_kind(g, "app.py", "models.py", EdgeKind.IMPORTS)

        # tests/test_auth.py -> auth.py : IMPORTS
        assert _has_edge_kind(g, "tests/test_auth.py", "auth.py", EdgeKind.IMPORTS)

        # tests/test_auth.py -> auth.py : TESTS
        assert _has_edge_kind(g, "tests/test_auth.py", "auth.py", EdgeKind.TESTS)

    def test_typescript_fixture_edges(self):
        """Verify edges per TypeScriptFixtureEdges contract."""
        files = _ts_fixture_files()
        g = build_graph(files)

        # auth.ts -> types.ts : IMPORTS
        assert _has_edge_kind(g, "auth.ts", "types.ts", EdgeKind.IMPORTS)

        # index.ts -> auth.ts : IMPORTS
        assert _has_edge_kind(g, "index.ts", "auth.ts", EdgeKind.IMPORTS)

        # index.ts -> types.ts : IMPORTS
        assert _has_edge_kind(g, "index.ts", "types.ts", EdgeKind.IMPORTS)

        # __tests__/auth.test.ts -> auth.ts : TESTS
        assert _has_edge_kind(g, "__tests__/auth.test.ts", "auth.ts", EdgeKind.TESTS)

    def test_edge_deduplication(self):
        """Duplicate refs to the same target with same kind should merge symbols."""
        fi = _make_fi(
            "a.py",
            refs=[
                Reference(
                    source_file="a.py", target_name="Foo", target_file="b.py", kind=EdgeKind.IMPORTS
                ),
                Reference(
                    source_file="a.py", target_name="Bar", target_file="b.py", kind=EdgeKind.IMPORTS
                ),
            ],
        )
        files = {
            "a.py": fi,
            "b.py": _make_fi(
                "b.py",
                symbols=[
                    _make_symbol("Foo", SymbolKind.CLASS, "b.py"),
                    _make_symbol("Bar", SymbolKind.FUNCTION, "b.py"),
                ],
            ),
        }
        g = build_graph(files)
        # Should have exactly one IMPORTS edge from a.py to b.py
        # The merged edge should have both symbols
        all_syms = []
        for _, _, d in g.edges("a.py", data=True):
            if d.get("kind") == EdgeKind.IMPORTS:
                all_syms.extend(d["symbols"])
        assert "Foo" in all_syms
        assert "Bar" in all_syms


# ===================================================================
# resolve_references
# ===================================================================


class TestResolveReferences:
    def test_python_relative_import(self):
        files = _python_fixture_files()
        resolved = resolve_references(files)
        # auth.py imports .models → should resolve to models.py
        auth_refs = [r for r in resolved if r.source_file == "auth.py"]
        assert any(r.target_file == "models.py" for r in auth_refs)

    def test_ts_relative_import(self):
        files = _ts_fixture_files()
        resolved = resolve_references(files)
        auth_refs = [r for r in resolved if r.source_file == "auth.ts"]
        assert any(r.target_file == "types.ts" for r in auth_refs)

    def test_unresolvable_skipped(self):
        """External/unresolvable references produce no output."""
        fi = _make_fi(
            "a.py",
            refs=[Reference(source_file="a.py", target_name="numpy", kind=EdgeKind.IMPORTS)],
        )
        files = {"a.py": fi}
        resolved = resolve_references(files)
        assert len(resolved) == 0

    def test_already_resolved_passthrough(self):
        """References with target_file already set pass through unchanged."""
        ref = Reference(source_file="a.py", target_name="X", target_file="b.py")
        fi = _make_fi("a.py", refs=[ref])
        files = {"a.py": fi, "b.py": _make_fi("b.py")}
        resolved = resolve_references(files)
        assert any(r.target_file == "b.py" for r in resolved)

    def test_c7_collision_returns_all(self):
        """When symbol collision can't be resolved, all targets are returned."""
        a = _make_fi(
            "pkg1/a.py",
            refs=[
                Reference(source_file="pkg1/a.py", target_name="Helper"),
            ],
        )
        b = _make_fi(
            "pkg2/helper.py",
            symbols=[
                _make_symbol("Helper", SymbolKind.CLASS, "pkg2/helper.py"),
            ],
        )
        c = _make_fi(
            "pkg3/helper.py",
            symbols=[
                _make_symbol("Helper", SymbolKind.CLASS, "pkg3/helper.py"),
            ],
        )
        files = {"pkg1/a.py": a, "pkg2/helper.py": b, "pkg3/helper.py": c}
        resolved = resolve_references(files)
        targets = {r.target_file for r in resolved if r.source_file == "pkg1/a.py"}
        assert "pkg2/helper.py" in targets
        assert "pkg3/helper.py" in targets

    def test_c7_same_dir_preferred(self):
        """C7: same-directory file preferred when symbol collides."""
        a = _make_fi(
            "pkg/a.py",
            refs=[
                Reference(source_file="pkg/a.py", target_name="Config"),
            ],
        )
        same_dir = _make_fi(
            "pkg/config.py",
            symbols=[
                _make_symbol("Config", SymbolKind.CLASS, "pkg/config.py"),
            ],
        )
        other_dir = _make_fi(
            "other/config.py",
            symbols=[
                _make_symbol("Config", SymbolKind.CLASS, "other/config.py"),
            ],
        )
        files = {"pkg/a.py": a, "pkg/config.py": same_dir, "other/config.py": other_dir}
        resolved = resolve_references(files)
        targets = [r.target_file for r in resolved if r.source_file == "pkg/a.py"]
        assert targets == ["pkg/config.py"]


# ===================================================================
# _detect_test_edges
# ===================================================================


class TestDetectTestEdges:
    def test_python_test_prefix(self):
        files = {
            "auth.py": _make_fi("auth.py"),
            "test_auth.py": _make_fi("test_auth.py"),
        }
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert _has_edge_kind(g, "test_auth.py", "auth.py", EdgeKind.TESTS)

    def test_python_test_suffix(self):
        files = {
            "auth.py": _make_fi("auth.py"),
            "auth_test.py": _make_fi("auth_test.py"),
        }
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert _has_edge_kind(g, "auth_test.py", "auth.py", EdgeKind.TESTS)

    def test_ts_test_file(self):
        files = {
            "auth.ts": _make_fi("auth.ts", language="typescript"),
            "auth.test.ts": _make_fi("auth.test.ts", language="typescript"),
        }
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert _has_edge_kind(g, "auth.test.ts", "auth.ts", EdgeKind.TESTS)

    def test_ts_tests_dir(self):
        files = _ts_fixture_files()
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert _has_edge_kind(g, "__tests__/auth.test.ts", "auth.ts", EdgeKind.TESTS)

    def test_go_test(self):
        files = {
            "auth.go": _make_fi("auth.go", language="go"),
            "auth_test.go": _make_fi("auth_test.go", language="go"),
        }
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert _has_edge_kind(g, "auth_test.go", "auth.go", EdgeKind.TESTS)

    def test_java_test(self):
        files = {
            "Auth.java": _make_fi("Auth.java", language="java"),
            "AuthTest.java": _make_fi("AuthTest.java", language="java"),
        }
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert _has_edge_kind(g, "AuthTest.java", "Auth.java", EdgeKind.TESTS)

    def test_no_match_no_edge(self):
        """Non-test files should not create TESTS edges."""
        files = {
            "auth.py": _make_fi("auth.py"),
            "utils.py": _make_fi("utils.py"),
        }
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert g.number_of_edges() == 0

    def test_tests_dir_to_parent(self):
        """tests/test_auth.py should find auth.py in the parent directory."""
        files = {
            "auth.py": _make_fi("auth.py"),
            "tests/test_auth.py": _make_fi("tests/test_auth.py"),
        }
        g = nx.MultiDiGraph()
        g.add_nodes_from(files.keys())
        _detect_test_edges(files, g)
        assert _has_edge_kind(g, "tests/test_auth.py", "auth.py", EdgeKind.TESTS)


# ===================================================================
# _normalize_path
# ===================================================================


def test_normalize_path_resolves_dotdot() -> None:
    assert _normalize_path("a/../b/c.py") == "b/c.py"


def test_normalize_path_removes_dot() -> None:
    assert _normalize_path("./a/b.py") == "a/b.py"


def test_normalize_path_no_change() -> None:
    assert _normalize_path("a/b/c.py") == "a/b/c.py"


# ===================================================================
# Helpers
# ===================================================================


def _has_edge_kind(g: nx.MultiDiGraph, src: str, tgt: str, kind: EdgeKind) -> bool:
    """Check if an edge with the given kind exists between src and tgt."""
    if not g.has_edge(src, tgt):
        return False
    for _, data in g[src][tgt].items():
        if data.get("kind") == kind:
            return True
    return False
