"""Tests for the codegraph CLI."""

from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from codegraph.cli import main


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def sample_repo(tmp_path):
    """Create a minimal repo for CLI tests."""
    (tmp_path / "models.py").write_text(
        '"""Data models."""\n\n\nclass User:\n    name: str\n\n\nclass Post:\n    title: str\n'
    )
    (tmp_path / "auth.py").write_text(
        "from models import User\n\n\ndef login(token: str) -> User:\n    return User()\n"
    )
    os.system(f"cd {tmp_path} && git init -q && git add -A && git commit -q -m init")
    return tmp_path


class TestVersion:
    def test_version_flag(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "codegraph" in result.output


class TestMapCommand:
    def test_map_default(self, runner, sample_repo):
        result = runner.invoke(main, ["map", str(sample_repo)])
        assert result.exit_code == 0
        assert len(result.output) > 0

    def test_map_with_budget(self, runner, sample_repo):
        result = runner.invoke(main, ["map", str(sample_repo), "--budget", "500"])
        assert result.exit_code == 0

    def test_map_json_format(self, runner, sample_repo):
        result = runner.invoke(main, ["map", str(sample_repo), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "files" in data


class TestContextCommand:
    def test_context_basic(self, runner, sample_repo):
        result = runner.invoke(main, ["context", str(sample_repo), "auth.py"])
        assert result.exit_code == 0

    def test_context_multiple_files(self, runner, sample_repo):
        result = runner.invoke(main, ["context", str(sample_repo), "auth.py", "models.py"])
        assert result.exit_code == 0

    def test_context_json(self, runner, sample_repo):
        result = runner.invoke(main, ["context", str(sample_repo), "auth.py", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "files" in data

    def test_context_no_files_error(self, runner, sample_repo):
        result = runner.invoke(main, ["context", str(sample_repo)])
        assert result.exit_code != 0


class TestQueryCommand:
    def test_query_basic(self, runner, sample_repo):
        result = runner.invoke(main, ["query", str(sample_repo), "authentication"])
        assert result.exit_code == 0

    def test_query_json(self, runner, sample_repo):
        result = runner.invoke(main, ["query", str(sample_repo), "user model", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "files" in data


class TestEvidenceCommand:
    def test_query_evidence_json(self, runner, sample_repo):
        result = runner.invoke(main, ["evidence", str(sample_repo), "--text", "login token"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["mode"] == "query"
        assert data["files"]
        assert data["files"][0]["path"] == "auth.py"

    def test_file_evidence_json(self, runner, sample_repo):
        result = runner.invoke(main, ["evidence", str(sample_repo), "--file", "auth.py"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["mode"] == "files"
        assert data["seed_files"] == ["auth.py"]

    def test_evidence_requires_one_input_mode(self, runner, sample_repo):
        result = runner.invoke(main, ["evidence", str(sample_repo), "--text", "login", "--file", "auth.py"])
        assert result.exit_code != 0


class TestStatsCommand:
    def test_stats_output(self, runner, sample_repo):
        result = runner.invoke(main, ["stats", str(sample_repo)])
        assert result.exit_code == 0
        assert "Files:" in result.output
        assert "Symbols:" in result.output
        assert "Edges:" in result.output
        assert "Languages:" in result.output


class TestClearCommand:
    def test_clear_existing_cache(self, runner, sample_repo):
        # First create a cache
        runner.invoke(main, ["map", str(sample_repo)])
        cache_dir = os.path.join(str(sample_repo), ".codegraph")
        assert os.path.isdir(cache_dir)

        # Then clear it
        result = runner.invoke(main, ["clear", str(sample_repo)])
        assert result.exit_code == 0
        assert "Cleared cache" in result.output
        assert not os.path.isdir(cache_dir)

    def test_clear_no_cache(self, runner, tmp_path):
        result = runner.invoke(main, ["clear", str(tmp_path)])
        assert result.exit_code == 0
        assert "No cache directory found" in result.output
