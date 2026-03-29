"""Tests for codegraph.ranker — PageRank-based file ranking."""

from __future__ import annotations

import networkx as nx

from codegraph.models import FileInfo, Symbol, SymbolKind
from codegraph.ranker import personalization_for_files, personalization_for_query, rank_files


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
