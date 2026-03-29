"""Shared pytest fixtures for codegraph tests."""

from __future__ import annotations

import os

import pytest

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def py_project() -> str:
    return os.path.join(_FIXTURES_DIR, "python_project")


@pytest.fixture
def ts_project() -> str:
    return os.path.join(_FIXTURES_DIR, "typescript_project")


@pytest.fixture
def mixed_project() -> str:
    return os.path.join(_FIXTURES_DIR, "mixed_project")


@pytest.fixture
def edge_cases() -> str:
    return os.path.join(_FIXTURES_DIR, "edge_cases")


@pytest.fixture
def single_file_project() -> str:
    return os.path.join(_FIXTURES_DIR, "single_file")
