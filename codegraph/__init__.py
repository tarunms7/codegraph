"""codegraph — Ranked, token-budget-aware code context for LLMs and AI agents."""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Literal

from codegraph.exceptions import CacheError, CodeGraphError, ParseError  # noqa: F401
from codegraph.models import EdgeKind, FileInfo, Reference, Symbol, SymbolKind

__version__ = "0.1.0"

__all__ = [
    "CodeGraph",
    "Symbol",
    "FileInfo",
    "Reference",
    "SymbolKind",
    "EdgeKind",
]

logger = logging.getLogger("codegraph")

Format = Literal["markdown", "json"]

# Directories to skip when walking (C10)
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    "dist",
    "build",
    "target",
    ".eggs",
}

_MAX_WALK_FILES = 10_000
_MAX_FILE_SIZE = 1_000_000  # 1MB


class CodeGraph:
    """Main entry point for codegraph — indexes a repository and provides ranked context."""

    def __init__(
        self,
        repo_path: str,
        *,
        cache: bool = True,
        languages: list[str] | None = None,
    ) -> None:
        self._repo_path = str(Path(repo_path).resolve())
        self._use_cache = cache
        self._languages = languages
        self._cache_hits = 0
        self._cache_misses = 0
        self._index_time_ms = 0.0
        self._files: dict[str, FileInfo] = {}
        self._graph = None
        self._cache_instance = None
        self._index()

    def _get_file_list(self) -> list[str]:
        """Get list of tracked files via git ls-files, falling back to directory walk."""
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=self._repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                files = [f for f in result.stdout.split("\0") if f]
                return [os.path.join(self._repo_path, f) for f in files]
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass

        # C10: fallback directory walk
        logger.warning(
            "Not a git repository, using directory walk. Results may include untracked files."
        )
        files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._repo_path):
            # Skip hidden and ignored directories
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
            # Skip directories matching egg-info pattern
            dirnames[:] = [d for d in dirnames if not d.endswith(".egg-info")]

            for fname in filenames:
                if len(files) >= _MAX_WALK_FILES:
                    logger.warning("File limit reached (%d), stopping walk.", _MAX_WALK_FILES)
                    return files
                full = os.path.join(dirpath, fname)
                try:
                    if os.path.getsize(full) > _MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                files.append(full)

        return files

    def _index(self) -> None:
        """Build or rebuild the file index and dependency graph."""
        from codegraph import graph as graph_mod
        from codegraph import parser as parser_mod
        from codegraph.cache import IndexCache
        from codegraph.languages import detect_language

        start = time.monotonic()
        self._cache_hits = 0
        self._cache_misses = 0

        # Get file list
        all_files = self._get_file_list()

        # Filter by supported languages and language filter
        filtered: list[str] = []
        for fp in all_files:
            lang = detect_language(fp)
            if lang is None:
                continue
            if self._languages and lang not in self._languages:
                continue
            filtered.append(fp)

        # Set up cache if enabled (C11)
        cache = None
        if self._use_cache:
            cache_dir = os.path.join(self._repo_path, ".codegraph")
            try:
                cache = IndexCache(cache_dir)
            except (CacheError, OSError) as exc:
                logger.warning("Cache init failed, proceeding without cache: %s", exc)
                cache = None
        self._cache_instance = cache

        # Parse files, using cache where possible
        files_dict: dict[str, FileInfo] = {}

        for fp in filtered:
            try:
                with open(fp, "rb") as f:
                    content_hash = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                continue

            rel_path = os.path.relpath(fp, self._repo_path)

            if cache is not None:
                try:
                    cached = cache.get(rel_path, content_hash)
                except CacheError:
                    cached = None
                if cached is not None:
                    files_dict[rel_path] = cached
                    self._cache_hits += 1
                    continue

            # Need to parse
            self._cache_misses += 1
            fi = parser_mod.parse_file(fp, self._repo_path)
            files_dict[fi.path] = fi

            if cache is not None:
                try:
                    cache.put(fi)
                except CacheError as exc:
                    logger.debug("Cache write failed for %s: %s", fi.path, exc)

        # Remove stale cache entries
        if cache is not None:
            try:
                cached_all = cache.get_all()
                for cached_path in cached_all:
                    if cached_path not in files_dict:
                        try:
                            cache.invalidate(cached_path)
                        except CacheError:
                            pass
            except CacheError:
                pass

        # Build graph
        self._files = files_dict
        self._graph = graph_mod.build_graph(files_dict)

        elapsed = (time.monotonic() - start) * 1000
        self._index_time_ms = elapsed
        logger.info(
            "Indexed %d files (%d cached, %d parsed) in %.1fms",
            len(files_dict),
            self._cache_hits,
            self._cache_misses,
            elapsed,
        )

    def context_for(
        self,
        files: list[str],
        token_budget: int = 4096,
        *,
        format: Format = "markdown",
    ) -> str:
        """Get ranked context relevant to specific files."""
        from codegraph import ranker as ranker_mod
        from codegraph import renderer as renderer_mod

        # C17: warn for nonexistent files, proceed with existing
        existing = []
        for f in files:
            if f in self._files:
                existing.append(f)
            else:
                logger.warning("File not in index: %s", f)

        if not existing:
            if format == "json":
                import json

                return json.dumps({"files": [], "error": "No matching files found"})
            return "<!-- No matching files found in index -->"

        p = ranker_mod.personalization_for_files(existing, self._graph)
        scores = ranker_mod.rank_files(self._graph, personalization=p)
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return renderer_mod.render_context(ranked, self._files, token_budget, format=format)

    def query(
        self,
        text: str,
        token_budget: int = 4096,
        *,
        format: Format = "markdown",
    ) -> str:
        """Get ranked context relevant to a natural language query."""
        from codegraph import ranker as ranker_mod
        from codegraph import renderer as renderer_mod

        p = ranker_mod.personalization_for_query(text, self._graph)
        scores = ranker_mod.rank_files(self._graph, personalization=p)
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return renderer_mod.render_context(ranked, self._files, token_budget, format=format)

    def repo_map(
        self,
        token_budget: int = 2048,
        *,
        format: Format = "markdown",
    ) -> str:
        """Get a global repo map ranked by structural importance."""
        from codegraph import ranker as ranker_mod
        from codegraph import renderer as renderer_mod

        scores = ranker_mod.rank_files(self._graph)
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return renderer_mod.render_context(ranked, self._files, token_budget, format=format)

    def refresh(self) -> None:
        """Re-scan the repository for changes and update the index (C18)."""
        self._index()

    @property
    def graph(self):
        """The underlying NetworkX dependency graph."""
        return self._graph

    @property
    def symbols(self) -> dict[str, list[Symbol]]:
        """All symbols indexed by file path."""
        return {path: fi.symbols for path, fi in self._files.items()}

    @property
    def stats(self) -> dict:
        """Index statistics per C14."""
        lang_counts: dict[str, int] = {}
        total_symbols = 0
        for fi in self._files.values():
            lang_counts[fi.language] = lang_counts.get(fi.language, 0) + 1
            total_symbols += len(fi.symbols)

        return {
            "files": len(self._files),
            "symbols": total_symbols,
            "edges": self._graph.number_of_edges() if self._graph else 0,
            "languages": lang_counts,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "index_time_ms": self._index_time_ms,
        }
