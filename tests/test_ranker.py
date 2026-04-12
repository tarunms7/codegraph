"""Tests for codegraph.ranker — PageRank-based file ranking."""

from __future__ import annotations

import networkx as nx

from codegraph.models import FileInfo, Symbol, SymbolKind
from codegraph.ranker import (
    personalization_for_files,
    personalization_for_query,
    rank_files,
    rank_for_files,
    rank_for_query,
)


def _make_fi(path: str, symbols: list[Symbol] | None = None) -> FileInfo:
    return FileInfo(
        path=path, language="python", content_hash="abc", symbols=symbols or [], lines=10
    )


def _simple_graph() -> nx.MultiDiGraph:
    """A → B → C, with file_info on each node."""
    g = nx.MultiDiGraph()
    for name in ("a.py", "b.py", "c.py"):
        g.add_node(name, file_info=_make_fi(name))
    g.add_edge("a.py", "b.py", kind="imports", symbols=["foo"])
    g.add_edge("b.py", "c.py", kind="imports", symbols=["bar"])
    return g


# ===================================================================
# rank_files
# ===================================================================


class TestRankFiles:
    def test_empty_graph(self):
        g = nx.MultiDiGraph()
        assert rank_files(g) == {}

    def test_single_node(self):
        g = nx.MultiDiGraph()
        g.add_node("only.py")
        result = rank_files(g)
        assert result == {"only.py": 1.0}

    def test_returns_all_nodes(self):
        g = _simple_graph()
        scores = rank_files(g)
        assert set(scores.keys()) == {"a.py", "b.py", "c.py"}

    def test_sorted_descending(self):
        g = _simple_graph()
        scores = rank_files(g)
        values = list(scores.values())
        assert values == sorted(values, reverse=True)

    def test_scores_sum_roughly_to_one(self):
        g = _simple_graph()
        scores = rank_files(g)
        assert abs(sum(scores.values()) - 1.0) < 0.01

    def test_personalization_biases_result(self):
        g = _simple_graph()
        p = {"a.py": 1.0, "b.py": 0.0, "c.py": 0.0}
        scores = rank_files(g, personalization=p)
        # a.py should be ranked highly
        ranked = list(scores.keys())
        assert ranked[0] == "a.py"

    def test_disconnected_nodes_get_rank(self):
        g = nx.MultiDiGraph()
        g.add_node("a.py")
        g.add_node("b.py")
        g.add_node("c.py")
        g.add_edge("a.py", "b.py", kind="imports", symbols=["x"])
        scores = rank_files(g)
        assert "c.py" in scores
        assert scores["c.py"] > 0

    def test_multi_edges_increase_weight(self):
        """Multiple edges between same pair should increase effective weight."""
        g = nx.MultiDiGraph()
        g.add_node("a.py")
        g.add_node("b.py")
        g.add_node("c.py")
        # a→b has 3 edges, a→c has 1
        g.add_edge("a.py", "b.py", kind="imports", symbols=["x"])
        g.add_edge("a.py", "b.py", kind="calls", symbols=["y"])
        g.add_edge("a.py", "b.py", kind="inherits", symbols=["z"])
        g.add_edge("a.py", "c.py", kind="imports", symbols=["w"])
        scores = rank_files(g)
        assert scores["b.py"] > scores["c.py"]


class TestHybridRanking:
    def test_rank_for_query_prioritizes_direct_lexical_match(self):
        g = nx.MultiDiGraph()
        g.add_node(
            "core.py",
            file_info=_make_fi(
                "core.py",
                symbols=[
                    Symbol(
                        name="Dispatcher",
                        kind=SymbolKind.CLASS,
                        file="core.py",
                        line=1,
                        signature="class Dispatcher",
                    ),
                ],
            ),
        )
        g.add_node(
            "daemon_executor.py",
            file_info=_make_fi(
                "daemon_executor.py",
                symbols=[
                    Symbol(
                        name="ExecutorMixin",
                        kind=SymbolKind.CLASS,
                        file="daemon_executor.py",
                        line=1,
                        signature="class ExecutorMixin",
                    ),
                ],
            ),
        )
        g.add_node("helpers.py", file_info=_make_fi("helpers.py"))

        # Make core.py structurally central, but the query targets daemon_executor.py directly.
        g.add_edge("helpers.py", "core.py", kind="imports", symbols=["a"])
        g.add_edge("daemon_executor.py", "core.py", kind="imports", symbols=["b"])
        g.add_edge("core.py", "helpers.py", kind="imports", symbols=["c"])

        scores = rank_for_query(g, "daemon executor")
        ranked = list(scores.keys())
        assert ranked[0] == "daemon_executor.py"

    def test_rank_for_query_prioritizes_exact_code_shaped_basename(self):
        g = nx.MultiDiGraph()
        g.add_node(
            "forge/tui/app.py",
            file_info=_make_fi(
                "forge/tui/app.py",
                symbols=[
                    Symbol(
                        name="DaemonApp",
                        kind=SymbolKind.CLASS,
                        file="forge/tui/app.py",
                        line=1,
                        signature="class DaemonApp",
                    ),
                ],
            ),
        )
        g.add_node(
            "forge/core/daemon_executor.py",
            file_info=_make_fi(
                "forge/core/daemon_executor.py",
                symbols=[
                    Symbol(
                        name="DaemonExecutor",
                        kind=SymbolKind.CLASS,
                        file="forge/core/daemon_executor.py",
                        line=1,
                        signature="class DaemonExecutor",
                    ),
                ],
            ),
        )
        g.add_edge("forge/tui/app.py", "forge/core/daemon_executor.py", kind="imports", symbols=["x"])
        g.add_edge("forge/core/daemon_executor.py", "forge/tui/app.py", kind="imports", symbols=["y"])

        scores = rank_for_query(g, "daemon executor")
        ranked = list(scores.keys())
        assert ranked[0] == "forge/core/daemon_executor.py"

    def test_rank_for_files_keeps_seed_file_first(self):
        g = _simple_graph()
        scores = rank_for_files(g, ["a.py"])
        ranked = list(scores.keys())
        assert ranked[0] == "a.py"
        assert ranked.index("b.py") < ranked.index("c.py")

    def test_rank_for_query_prefers_source_file_over_test_when_query_is_general(self):
        g = nx.MultiDiGraph()
        g.add_node(
            "unified_planner.py",
            file_info=_make_fi(
                "unified_planner.py",
                symbols=[
                    Symbol(
                        name="UnifiedPlanner",
                        kind=SymbolKind.CLASS,
                        file="unified_planner.py",
                        line=1,
                        signature="class UnifiedPlanner",
                    ),
                ],
            ),
        )
        g.add_node(
            "unified_planner_test.py",
            file_info=_make_fi(
                "unified_planner_test.py",
                symbols=[
                    Symbol(
                        name="test_unified_planner",
                        kind=SymbolKind.FUNCTION,
                        file="unified_planner_test.py",
                        line=1,
                        signature="def test_unified_planner()",
                    ),
                ],
            ),
        )
        g.add_edge("unified_planner_test.py", "unified_planner.py", kind="tests", symbols=["x"])

        scores = rank_for_query(g, "unified planner")
        ranked = list(scores.keys())
        assert ranked[0] == "unified_planner.py"


# ===================================================================
# personalization_for_files
# ===================================================================


class TestPersonalizationForFiles:
    def test_matching_files(self):
        g = _simple_graph()
        p = personalization_for_files(["a.py", "c.py"], g)
        assert p is not None
        assert p["a.py"] == 1.0
        assert p["c.py"] == 1.0
        assert p["b.py"] == 0.0

    def test_no_matching_files(self):
        g = _simple_graph()
        p = personalization_for_files(["nonexistent.py"], g)
        assert p is None

    def test_partial_match(self):
        g = _simple_graph()
        p = personalization_for_files(["a.py", "nonexistent.py"], g)
        assert p is not None
        assert p["a.py"] == 1.0

    def test_empty_files_list(self):
        g = _simple_graph()
        p = personalization_for_files([], g)
        assert p is None


# ===================================================================
# personalization_for_query
# ===================================================================


class TestPersonalizationForQuery:
    def test_path_match(self):
        g = _simple_graph()
        p = personalization_for_query("a", g)
        assert p is not None
        assert p["a.py"] > 0

    def test_symbol_match(self):
        g = nx.MultiDiGraph()
        fi = _make_fi(
            "auth.py",
            symbols=[
                Symbol(
                    name="authenticate",
                    kind=SymbolKind.FUNCTION,
                    file="auth.py",
                    line=1,
                    signature="def authenticate()",
                ),
            ],
        )
        g.add_node("auth.py", file_info=fi)
        g.add_node("utils.py", file_info=_make_fi("utils.py"))
        p = personalization_for_query("authenticate", g)
        assert p is not None
        assert p["auth.py"] > 0
        assert p["utils.py"] == 0.0

    def test_no_match_returns_none(self):
        g = _simple_graph()
        p = personalization_for_query("zzzznonexistent", g)
        assert p is None

    def test_empty_query(self):
        g = _simple_graph()
        p = personalization_for_query("", g)
        assert p is None

    def test_case_insensitive(self):
        g = nx.MultiDiGraph()
        fi = _make_fi(
            "Auth.py",
            symbols=[
                Symbol(
                    name="AuthService",
                    kind=SymbolKind.CLASS,
                    file="Auth.py",
                    line=1,
                    signature="class AuthService",
                ),
            ],
        )
        g.add_node("Auth.py", file_info=fi)
        p = personalization_for_query("auth", g)
        assert p is not None
        assert p["Auth.py"] > 0

    def test_multiple_keyword_weights(self):
        g = nx.MultiDiGraph()
        fi1 = _make_fi(
            "auth.py",
            symbols=[
                Symbol(
                    name="auth_login",
                    kind=SymbolKind.FUNCTION,
                    file="auth.py",
                    line=1,
                    signature="def auth_login()",
                ),
            ],
        )
        fi2 = _make_fi("utils.py")
        g.add_node("auth.py", file_info=fi1)
        g.add_node("utils.py", file_info=fi2)
        # "auth" matches both path and symbol name for auth.py
        p = personalization_for_query("auth", g)
        assert p is not None
        assert p["auth.py"] > 1  # matches in both path and symbol
