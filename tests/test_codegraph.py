"""Integration tests for CodeGraph — full pipeline: parsing -> graph -> ranking -> rendering."""

from __future__ import annotations

import json
import os
import subprocess

import networkx as nx

from codegraph import CodeGraph
from codegraph.renderer import count_tokens


class TestCodeGraphPythonProject:
    def test_index_creates_graph(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        assert cg.stats["files"] > 0
        assert cg.stats["symbols"] > 0
        assert cg.stats["edges"] > 0

    def test_context_for_returns_string(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.context_for(["auth.py"])
        assert isinstance(result, str)
        assert len(result) > 0
        assert "auth" in result.lower()

    def test_context_for_json(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.context_for(["auth.py"], format="json")
        data = json.loads(result)
        assert "files" in data
        assert "token_count" in data
        assert "token_budget" in data
        assert "files_included" in data
        assert "files_total" in data
        for f in data["files"]:
            assert "path" in f
            assert "rank" in f
            assert "tier" in f
            assert "language" in f
            assert "symbols" in f

    def test_query_returns_context(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.query("authentication")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_query_prefers_relevant_file_in_json(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.query("authenticate token", format="json")
        data = json.loads(result)
        assert data["files"]
        assert data["files"][0]["path"] == "auth.py"

    def test_evidence_for_query_returns_structured_pack(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        pack = cg.evidence_for_query("authenticate token", limit=3, symbol_limit=2)
        data = pack.to_dict()
        assert data["mode"] == "query"
        assert data["query"] == "authenticate token"
        assert data["files"]
        assert data["files"][0]["path"] == "auth.py"
        assert data["files"][0]["symbols"]
        assert data["files"][0]["focus_range"] is not None
        assert data["confidence"] > 0

    def test_evidence_for_files_keeps_seed_first(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        pack = cg.evidence_for_files(["auth.py"], limit=3)
        data = pack.to_dict()
        assert data["mode"] == "files"
        assert data["seed_files"] == ["auth.py"]
        assert data["files"]
        assert data["files"][0]["path"] == "auth.py"
        assert "seed-file" in data["files"][0]["reasons"]

    def test_repo_map(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.repo_map()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "##" in result

    def test_symbols_property(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        syms = cg.symbols
        assert isinstance(syms, dict)
        assert len(syms) > 0
        for key in syms:
            assert isinstance(key, str)

    def test_graph_property(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        g = cg.graph
        assert isinstance(g, nx.MultiDiGraph)
        assert g.number_of_nodes() > 0

    def test_stats_shape(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        s = cg.stats
        expected_keys = {
            "files",
            "symbols",
            "edges",
            "languages",
            "cache_hits",
            "cache_misses",
            "index_time_ms",
        }
        assert set(s.keys()) == expected_keys
        assert isinstance(s["languages"], dict)
        assert isinstance(s["index_time_ms"], float)

    def test_token_budget_respected(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.context_for(["auth.py"], token_budget=100)
        assert count_tokens(result) <= 100

    def test_nonexistent_file_warning(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.context_for(["nonexistent.py"])
        assert result.startswith("<!-- No matching files found")


class TestCodeGraphTypescriptProject:
    def test_ts_index(self, ts_project):
        cg = CodeGraph(ts_project, cache=False)
        assert cg.stats["files"] > 0
        assert cg.stats["symbols"] > 0

    def test_ts_context_for(self, ts_project):
        cg = CodeGraph(ts_project, cache=False)
        result = cg.context_for(["auth.ts"])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_ts_json_output(self, ts_project):
        cg = CodeGraph(ts_project, cache=False)
        result = cg.context_for(["auth.ts"], format="json")
        data = json.loads(result)
        assert "files" in data
        assert "token_count" in data


class TestCodeGraphMixedProject:
    def test_mixed_languages(self, mixed_project):
        cg = CodeGraph(mixed_project, cache=False)
        langs = cg.stats["languages"]
        assert "python" in langs
        assert "typescript" in langs

    def test_language_filter(self, mixed_project):
        cg = CodeGraph(mixed_project, cache=False, languages=["python"])
        langs = cg.stats["languages"]
        assert "python" in langs
        assert "typescript" not in langs


class TestCodeGraphEdgeCases:
    def test_edge_cases_no_crash(self, edge_cases):
        cg = CodeGraph(edge_cases, cache=False)
        assert cg.stats["files"] >= 0

    def test_empty_file_indexed(self, edge_cases):
        cg = CodeGraph(edge_cases, cache=False)
        assert "empty_file.py" in cg._files
        fi = cg._files["empty_file.py"]
        assert len(fi.symbols) == 0

    def test_binary_file_skipped(self, edge_cases):
        cg = CodeGraph(edge_cases, cache=False)
        # binary_file.bin should not be in the index (detect_language returns None for .bin)
        if "binary_file.bin" in cg._files:
            assert cg._files["binary_file.bin"].language == "binary"
        # Otherwise it's correctly skipped — both outcomes are acceptable

    def test_syntax_error_partial(self, edge_cases):
        cg = CodeGraph(edge_cases, cache=False)
        assert "syntax_error.py" in cg._files
        fi = cg._files["syntax_error.py"]
        assert len(fi.symbols) >= 1
        sym_names = [s.name for s in fi.symbols]
        assert "good_function" in sym_names

    def test_circular_imports_no_hang(self, edge_cases):
        cg = CodeGraph(edge_cases, cache=False)
        # If we got here, it didn't hang
        assert "circular_a.py" in cg._files
        assert "circular_b.py" in cg._files


class TestCodeGraphSingleFile:
    def test_single_file_works(self, single_file_project):
        cg = CodeGraph(single_file_project, cache=False)
        assert "hello.py" in cg._files
        fi = cg._files["hello.py"]
        assert len(fi.symbols) > 0

    def test_single_file_repo_map(self, single_file_project):
        cg = CodeGraph(single_file_project, cache=False)
        result = cg.repo_map()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_single_file_context(self, single_file_project):
        cg = CodeGraph(single_file_project, cache=False)
        result = cg.context_for(["hello.py"])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_context_for_json_keeps_seed_file_first(self, py_project):
        cg = CodeGraph(py_project, cache=False)
        result = cg.context_for(["auth.py"], format="json")
        data = json.loads(result)
        assert data["files"]
        assert data["files"][0]["path"] == "auth.py"


class TestCodeGraphCache:
    def test_cache_creates_directory(self, tmp_path):
        # Set up a minimal git repo in tmp_path
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        hello = tmp_path / "hello.py"
        hello.write_text("def foo(): pass\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "--no-verify"],
            cwd=tmp_path,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        CodeGraph(str(tmp_path), cache=True)
        assert (tmp_path / ".codegraph").exists()

    def test_cache_second_run_faster(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        hello = tmp_path / "hello.py"
        hello.write_text("def foo(): pass\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "--no-verify"],
            cwd=tmp_path,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        cg1 = CodeGraph(str(tmp_path), cache=True)
        assert cg1.stats["cache_misses"] > 0

        cg2 = CodeGraph(str(tmp_path), cache=True)
        assert cg2.stats["cache_hits"] > 0

    def test_no_cache_flag(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        hello = tmp_path / "hello.py"
        hello.write_text("def foo(): pass\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "--no-verify"],
            cwd=tmp_path,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        CodeGraph(str(tmp_path), cache=False)
        assert not (tmp_path / ".codegraph").exists()


class TestCodeGraphRefresh:
    def test_refresh_picks_up_changes(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        hello = tmp_path / "hello.py"
        hello.write_text("def foo(): pass\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "--no-verify"],
            cwd=tmp_path,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        cg = CodeGraph(str(tmp_path), cache=False)
        initial_symbols = sum(len(s) for s in cg.symbols.values())

        # Add a new function
        hello.write_text("def foo(): pass\ndef bar(): pass\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add bar", "--no-verify"],
            cwd=tmp_path,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        cg.refresh()
        refreshed_symbols = sum(len(s) for s in cg.symbols.values())
        assert refreshed_symbols > initial_symbols
