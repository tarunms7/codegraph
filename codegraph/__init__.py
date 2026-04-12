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
from codegraph.models import (
    EdgeKind,
    EvidenceFile,
    EvidenceNeighbor,
    EvidencePack,
    EvidenceSymbol,
    FileInfo,
    Reference,
    Symbol,
    SymbolKind,
)

__version__ = "0.1.0"

__all__ = [
    "CodeGraph",
    "resolve_cache_dir",
    "Symbol",
    "FileInfo",
    "Reference",
    "SymbolKind",
    "EdgeKind",
    "EvidenceSymbol",
    "EvidenceNeighbor",
    "EvidenceFile",
    "EvidencePack",
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


def resolve_cache_dir(repo_path: str, explicit_cache_dir: str | None = None) -> str:
    """Resolve the cache directory for a repo, honoring explicit overrides."""
    if explicit_cache_dir:
        return str(Path(explicit_cache_dir).expanduser().resolve())

    env_cache_dir = os.getenv("CODEGRAPH_CACHE_DIR", "").strip()
    if env_cache_dir:
        return str(Path(env_cache_dir).expanduser().resolve())

    return os.path.join(repo_path, ".codegraph")


class CodeGraph:
    """Main entry point for codegraph — indexes a repository and provides ranked context."""

    def __init__(
        self,
        repo_path: str,
        *,
        cache: bool = True,
        cache_dir: str | None = None,
        languages: list[str] | None = None,
    ) -> None:
        self._repo_path = str(Path(repo_path).resolve())
        if not Path(self._repo_path).exists():
            raise CodeGraphError(f"repo_path does not exist: {self._repo_path}")
        if Path(self._repo_path).is_file():
            raise CodeGraphError(f"repo_path must be a directory, got a file: {self._repo_path}")
        self._use_cache = cache
        self._cache_dir = resolve_cache_dir(self._repo_path, cache_dir) if cache else None
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
            try:
                cache = IndexCache(self._cache_dir or os.path.join(self._repo_path, ".codegraph"))
            except (CacheError, OSError) as exc:
                logger.warning("Cache init failed, proceeding without cache: %s", exc)
                cache = None
        self._cache_instance = cache

        # First pass: read each file once, compute SHA-256, check cache.
        # Collect uncached files with their already-read bytes.
        files_dict: dict[str, FileInfo] = {}
        uncached: list[str] = []
        uncached_bytes: dict[str, bytes] = {}

        for fp in filtered:
            try:
                with open(fp, "rb") as f:
                    file_bytes = f.read()
            except OSError:
                continue

            # Skip binary files (null byte in first 8KB)
            if b"\x00" in file_bytes[:8192]:
                rel_path = os.path.relpath(fp, self._repo_path)
                files_dict[rel_path] = FileInfo(path=rel_path, language="binary", content_hash="")
                continue

            content_hash = hashlib.sha256(file_bytes).hexdigest()
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

            # Need to parse — save already-read bytes
            self._cache_misses += 1
            uncached.append(fp)
            uncached_bytes[fp] = file_bytes

        # Second pass: parse uncached files in parallel, passing pre-read bytes
        if uncached:
            parsed = parser_mod.parse_files(uncached, self._repo_path, raw_bytes_map=uncached_bytes)
            for rel_path, fi in parsed.items():
                files_dict[rel_path] = fi
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
        if token_budget <= 0:
            raise CodeGraphError(f"token_budget must be positive, got {token_budget}")
        if not files:
            return ""
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

        scores = ranker_mod.rank_for_files(self._graph, existing)
        ranked = list(scores.items())
        return renderer_mod.render_context(ranked, self._files, token_budget, format=format)

    def query(
        self,
        text: str,
        token_budget: int = 4096,
        *,
        format: Format = "markdown",
    ) -> str:
        """Get ranked context relevant to a natural language query."""
        if token_budget <= 0:
            raise CodeGraphError(f"token_budget must be positive, got {token_budget}")
        if not text or not text.strip():
            return ""
        from codegraph import ranker as ranker_mod
        from codegraph import renderer as renderer_mod

        scores = ranker_mod.rank_for_query(self._graph, text)
        ranked = list(scores.items())
        return renderer_mod.render_context(ranked, self._files, token_budget, format=format)

    def repo_map(
        self,
        token_budget: int = 2048,
        *,
        format: Format = "markdown",
    ) -> str:
        """Get a global repo map ranked by structural importance."""
        if token_budget <= 0:
            raise CodeGraphError(f"token_budget must be positive, got {token_budget}")
        from codegraph import ranker as ranker_mod
        from codegraph import renderer as renderer_mod

        scores = ranker_mod.rank_files(self._graph)
        ranked = list(scores.items())
        return renderer_mod.render_context(ranked, self._files, token_budget, format=format)

    def evidence_for_query(
        self,
        text: str,
        *,
        limit: int = 8,
        symbol_limit: int = 5,
        neighbor_limit: int = 3,
    ) -> EvidencePack:
        """Return structured evidence for a natural-language query."""
        from codegraph import retrieval as retrieval_mod

        return retrieval_mod.build_evidence_for_query(
            self._graph,
            self._files,
            text,
            limit=limit,
            symbol_limit=symbol_limit,
            neighbor_limit=neighbor_limit,
        )

    def evidence_for_files(
        self,
        files: list[str],
        *,
        limit: int = 8,
        symbol_limit: int = 5,
        neighbor_limit: int = 3,
    ) -> EvidencePack:
        """Return structured evidence for file-seeded retrieval."""
        from codegraph import retrieval as retrieval_mod

        return retrieval_mod.build_evidence_for_files(
            self._graph,
            self._files,
            files,
            limit=limit,
            symbol_limit=symbol_limit,
            neighbor_limit=neighbor_limit,
        )

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
