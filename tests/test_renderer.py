"""Tests for codegraph.renderer — token-budget-aware context rendering."""

from __future__ import annotations

import json

from codegraph.models import FileInfo, Symbol, SymbolKind
from codegraph.renderer import count_tokens, render_context


def _make_symbol(
    name: str,
    kind: SymbolKind = SymbolKind.FUNCTION,
    line: int = 1,
    sig: str = "",
    parent: str | None = None,
) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file="test.py",
        line=line,
        signature=sig or f"def {name}()",
        parent=parent,
    )


def _make_fi(path: str, language: str = "python", symbols: list[Symbol] | None = None) -> FileInfo:
    return FileInfo(
        path=path,
        language=language,
        content_hash="abc",
        symbols=symbols or [],
        lines=10,
    )


# ===================================================================
# count_tokens
# ===================================================================


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_known_string(self):
        result = count_tokens("hello world")
        assert result > 0
        assert isinstance(result, int)

    def test_consistency(self):
        text = "def foo(): pass"
        assert count_tokens(text) == count_tokens(text)


# ===================================================================
# render_context — markdown
# ===================================================================


class TestRenderMarkdown:
    def test_empty_files(self):
        result = render_context([], {}, 1000, format="markdown")
        assert "## Relevant Context" in result
        assert "No files to display" in result

    def test_budget_zero_returns_empty(self):
        result = render_context([], {}, 0, format="markdown")
        assert result == ""

    def test_tier1_has_signatures(self):
        fi = _make_fi(
            "auth.py",
            symbols=[
                _make_symbol("authenticate", sig="def authenticate(token: str) -> User"),
                _make_symbol("authorize", sig="def authorize(user: User, perm: str) -> bool"),
            ],
        )
        ranked = [("auth.py", 0.9)]
        result = render_context(ranked, {"auth.py": fi}, 5000)
        assert "### auth.py" in result
        assert "def authenticate(token: str) -> User" in result
        assert "def authorize(user: User, perm: str) -> bool" in result

    def test_tier2_has_names_only(self):
        """With enough files, tier 2 files show only symbol names."""
        symbols = [_make_symbol(f"func_{i}", sig=f"def func_{i}(x: int) -> str") for i in range(3)]
        files = {}
        ranked = []
        # Need at least 4 files to get distinct tiers
        for i in range(10):
            path = f"file_{i}.py"
            fi = _make_fi(path, symbols=symbols)
            files[path] = fi
            ranked.append((path, 1.0 - i * 0.05))

        result = render_context(ranked, files, 50000)
        # Tier 2 files (index 3-5) should have names listed
        # Look for bullet-style name listing
        assert "- func_0" in result

    def test_tier3_related_files(self):
        """Tier 3 files appear in Related files section."""
        files = {}
        ranked = []
        for i in range(10):
            path = f"file_{i}.py"
            fi = _make_fi(path, symbols=[_make_symbol(f"sym_{i}")])
            files[path] = fi
            ranked.append((path, 1.0 - i * 0.05))

        result = render_context(ranked, files, 50000)
        assert "### Related files" in result

    def test_respects_token_budget(self):
        """Output should not exceed token budget."""
        symbols = [
            _make_symbol(f"func_{i}", sig=f"def func_{i}(x: int, y: str, z: float) -> dict")
            for i in range(20)
        ]
        fi = _make_fi("big.py", symbols=symbols)
        ranked = [("big.py", 1.0)]
        budget = 50
        result = render_context(ranked, {"big.py": fi}, budget)
        assert count_tokens(result) <= budget or result == ""

    def test_progressive_trimming(self):
        """When Tier 1 alone exceeds budget, symbols are trimmed."""
        symbols = [_make_symbol(f"func_{i}", sig=f"def func_{i}(x: int) -> str") for i in range(50)]
        fi = _make_fi("big.py", symbols=symbols)
        ranked = [("big.py", 1.0)]
        budget = 100
        result = render_context(ranked, {"big.py": fi}, budget)
        tokens = count_tokens(result)
        assert tokens <= budget

    def test_summary_from_symbols(self):
        """C9 fallback: summary generated from symbol names."""
        fi = _make_fi(
            "utils.py",
            symbols=[
                _make_symbol("helper_a"),
                _make_symbol("helper_b"),
            ],
        )
        ranked = [("utils.py", 0.9)]
        result = render_context(ranked, {"utils.py": fi}, 5000)
        assert "Defines:" in result


# ===================================================================
# render_context — JSON
# ===================================================================


class TestRenderJson:
    def test_budget_zero_returns_minimal_json(self):
        ranked = [("a.py", 0.5)]
        result = render_context(ranked, {}, 0, format="json")
        data = json.loads(result)
        assert data["files"] == []
        assert data["token_count"] == 0
        assert data["token_budget"] == 0
        assert data["files_included"] == 0
        assert data["files_total"] == 1

    def test_valid_json_schema(self):
        fi = _make_fi(
            "auth.py",
            symbols=[
                _make_symbol(
                    "authenticate",
                    kind=SymbolKind.FUNCTION,
                    sig="def authenticate(token: str) -> User",
                ),
            ],
        )
        ranked = [("auth.py", 0.9)]
        result = render_context(ranked, {"auth.py": fi}, 5000, format="json")
        data = json.loads(result)

        assert "files" in data
        assert "token_count" in data
        assert "token_budget" in data
        assert "files_included" in data
        assert "files_total" in data

        assert data["token_budget"] == 5000
        assert data["files_total"] == 1
        assert len(data["files"]) > 0

        f = data["files"][0]
        assert f["path"] == "auth.py"
        assert f["tier"] in (1, 2, 3)
        assert isinstance(f["rank"], float)
        assert isinstance(f["symbols"], list)

    def test_tier1_full_signatures(self):
        fi = _make_fi(
            "auth.py",
            symbols=[
                _make_symbol(
                    "authenticate",
                    kind=SymbolKind.FUNCTION,
                    sig="def authenticate(token: str) -> User",
                ),
            ],
        )
        ranked = [("auth.py", 0.9)]
        result = render_context(ranked, {"auth.py": fi}, 5000, format="json")
        data = json.loads(result)
        sym = data["files"][0]["symbols"][0]
        assert sym["name"] == "authenticate"
        assert sym["kind"] == "function"
        assert "token: str" in sym["signature"]
        assert sym["line"] == 1

    def test_tier3_empty_symbols(self):
        """Tier 3 files should have empty symbols array."""
        files = {}
        ranked = []
        for i in range(10):
            path = f"f{i}.py"
            fi = _make_fi(path, symbols=[_make_symbol(f"s{i}")])
            files[path] = fi
            ranked.append((path, 1.0 - i * 0.05))

        result = render_context(ranked, files, 50000, format="json")
        data = json.loads(result)
        tier3_files = [f for f in data["files"] if f["tier"] == 3]
        for f in tier3_files:
            assert f["symbols"] == []

    def test_json_respects_budget(self):
        """JSON output should fit within token budget."""
        symbols = [_make_symbol(f"func_{i}", sig=f"def func_{i}(x: int) -> str") for i in range(20)]
        files = {}
        ranked = []
        for i in range(10):
            path = f"module_{i}.py"
            fi = _make_fi(path, symbols=symbols)
            files[path] = fi
            ranked.append((path, 1.0 - i * 0.05))

        budget = 500
        result = render_context(ranked, files, budget, format="json")
        assert count_tokens(result) <= budget

    def test_json_small_budget_keeps_compacted_entry(self):
        fi = _make_fi(
            "auth.py",
            symbols=[
                _make_symbol("authenticate", sig="def authenticate(token: str) -> User"),
                _make_symbol("authorize", sig="def authorize(user: User, perm: str) -> bool"),
            ],
        )
        ranked = [("auth.py", 0.9)]
        result = render_context(ranked, {"auth.py": fi}, 120, format="json")
        data = json.loads(result)
        assert data["files_included"] >= 1
        assert data["files"][0]["path"] == "auth.py"
        assert count_tokens(result) <= 120

    def test_token_count_accurate(self):
        fi = _make_fi("a.py", symbols=[_make_symbol("foo")])
        ranked = [("a.py", 0.9)]
        result = render_context(ranked, {"a.py": fi}, 5000, format="json")
        data = json.loads(result)
        actual = count_tokens(result)
        # token_count should be close to actual (may differ slightly due to re-serialization)
        assert abs(data["token_count"] - actual) <= 5

    def test_files_included_count(self):
        files = {}
        ranked = []
        for i in range(5):
            path = f"f{i}.py"
            files[path] = _make_fi(path)
            ranked.append((path, 1.0 - i * 0.1))

        result = render_context(ranked, files, 5000, format="json")
        data = json.loads(result)
        assert data["files_included"] == len(data["files"])
        assert data["files_total"] == 5

    def test_symbol_parent_field(self):
        fi = _make_fi(
            "cls.py",
            symbols=[
                _make_symbol(
                    "method", kind=SymbolKind.METHOD, sig="def method(self)", parent="MyClass"
                ),
                _make_symbol("top_func", kind=SymbolKind.FUNCTION, sig="def top_func()"),
            ],
        )
        ranked = [("cls.py", 0.9)]
        result = render_context(ranked, {"cls.py": fi}, 5000, format="json")
        data = json.loads(result)
        syms = data["files"][0]["symbols"]
        method = next(s for s in syms if s["name"] == "method")
        func = next(s for s in syms if s["name"] == "top_func")
        assert method["parent"] == "MyClass"
        assert func["parent"] is None


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    def test_missing_file_info(self):
        """render_context handles file paths not in file_infos gracefully."""
        ranked = [("missing.py", 0.9)]
        result = render_context(ranked, {}, 5000)
        assert "### missing.py" in result

    def test_single_file(self):
        fi = _make_fi("only.py", symbols=[_make_symbol("main")])
        ranked = [("only.py", 1.0)]
        result = render_context(ranked, {"only.py": fi}, 5000)
        assert "### only.py" in result

    def test_tier1_overflow_still_renders_tier2(self):
        """When first tier 1 file overflows, remaining tier 1 files still render.

        With `break` (old code), the tier 1 loop exits after trimming big.py,
        so small_1.py and small_2.py (also tier 1) are skipped.
        With `continue` (fixed code), they are still processed.
        """
        # Create 10 files so tier partitioning gives us:
        #   tier1 = [big.py, small_1.py, small_2.py]  (indices 0-2)
        #   tier2 = [small_3.py, small_4.py, small_5.py]  (indices 3-5)
        # big.py has very expensive symbols: each signature is so long that
        # even 1 symbol in the trimmed output exceeds the per-file remaining
        # budget. _render_tier1_md_trimmed returns just the bare header (~5
        # tokens), leaving plenty of budget for subsequent files.
        long_param_list = ", ".join(f"p{j}: int" for j in range(40))
        big_symbols = [
            _make_symbol(
                f"func_{i}",
                sig=f"def func_{i}({long_param_list}) -> None",
            )
            for i in range(30)
        ]
        small_symbols = [_make_symbol("small_fn", sig="def small_fn()")]

        files = {}
        ranked = []
        files["big.py"] = _make_fi("big.py", symbols=big_symbols)
        ranked.append(("big.py", 1.0))
        for i in range(1, 10):
            path = f"small_{i}.py"
            files[path] = _make_fi(path, symbols=small_symbols)
            ranked.append((path, 0.9 - i * 0.05))

        # Budget: big.py full section hugely exceeds this. Even 1 trimmed
        # symbol + overhead > remaining, so trimmer returns just the header
        # (~5 tokens). This leaves ~195 tokens for remaining tier 1/2 files.
        budget = 200
        result = render_context(ranked, files, budget)

        assert count_tokens(result) <= budget
        # Key assertion: small_1.py or small_2.py (tier 1 files AFTER big.py)
        # must appear. With the old `break`, they would be skipped entirely.
        assert "### small_1.py" in result or "### small_2.py" in result, (
            f"Remaining tier 1 files missing after overflow:\n{result}"
        )

    def test_empty_ranked_files_with_budget(self):
        """render_context([], {}, 1000) includes 'No files' indication."""
        result = render_context([], {}, 1000, format="markdown")
        assert "No files to display" in result
        assert "## Relevant Context" in result

    def test_large_tier_partitioning(self):
        """Verify tier partitioning with many files."""
        files = {}
        ranked = []
        for i in range(20):
            path = f"f{i:02d}.py"
            files[path] = _make_fi(path, symbols=[_make_symbol(f"sym_{i}")])
            ranked.append((path, 1.0 - i * 0.01))

        result = render_context(ranked, files, 50000, format="json")
        data = json.loads(result)
        tiers = {f["tier"] for f in data["files"]}
        assert 1 in tiers
        assert 2 in tiers
        assert 3 in tiers
        # Tier 4 should NOT appear
        assert 4 not in tiers
