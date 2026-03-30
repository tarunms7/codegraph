"""SQLite persistent cache with content-hash invalidation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time

from codegraph.exceptions import CacheError
from codegraph.models import EdgeKind, FileInfo, Reference, Symbol, SymbolKind

logger = logging.getLogger("codegraph")

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    language TEXT NOT NULL,
    lines INTEGER NOT NULL,
    symbols_json TEXT NOT NULL,
    references_json TEXT NOT NULL,
    indexed_at REAL NOT NULL
);
"""

_CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_content_hash ON files(content_hash);
"""


def _serialize_symbols(symbols: list[Symbol]) -> str:
    return json.dumps(
        [
            {
                "name": s.name,
                "kind": s.kind.value,
                "file": s.file,
                "line": s.line,
                "signature": s.signature,
                "parent": s.parent,
                "end_line": s.end_line,
            }
            for s in symbols
        ]
    )


def _deserialize_symbols(json_str: str) -> list[Symbol]:
    return [
        Symbol(
            name=d["name"],
            kind=SymbolKind(d["kind"]),
            file=d["file"],
            line=d["line"],
            signature=d["signature"],
            parent=d.get("parent"),
            end_line=d.get("end_line"),
        )
        for d in json.loads(json_str)
    ]


def _serialize_references(refs: list[Reference]) -> str:
    return json.dumps(
        [
            {
                "source_file": r.source_file,
                "target_name": r.target_name,
                "target_file": r.target_file,
                "line": r.line,
                "kind": r.kind.value,
            }
            for r in refs
        ]
    )


def _deserialize_references(json_str: str) -> list[Reference]:
    return [
        Reference(
            source_file=d["source_file"],
            target_name=d["target_name"],
            target_file=d.get("target_file"),
            line=d.get("line", 0),
            kind=EdgeKind(d["kind"]),
        )
        for d in json.loads(json_str)
    ]


def _row_to_fileinfo(row: sqlite3.Row | tuple) -> FileInfo:
    path, content_hash, language, lines, symbols_json, references_json, _indexed_at = row
    return FileInfo(
        path=path,
        language=language,
        content_hash=content_hash,
        symbols=_deserialize_symbols(symbols_json),
        references=_deserialize_references(references_json),
        lines=lines,
    )


class IndexCache:
    """SQLite-backed persistent cache for parsed file metadata."""

    def __init__(self, cache_dir: str) -> None:
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except PermissionError:
            repo_hash = hashlib.sha256(cache_dir.encode()).hexdigest()[:16]
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "codegraph", repo_hash)
            os.makedirs(cache_dir, exist_ok=True)
        db_path = os.path.join(cache_dir, "index.db")
        logger.debug("Cache location: %s", db_path)
        self._lock = threading.Lock()
        self._closed = False
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute(_CREATE_TABLE)
            self._conn.execute(_CREATE_INDEX)
            self._conn.commit()
        except sqlite3.DatabaseError as exc:
            logger.warning("Cache database corrupted, recreating: %s", exc)
            self._conn = None  # type: ignore[assignment]
            try:
                os.remove(db_path)
            except OSError:
                pass
            try:
                self._conn = sqlite3.connect(db_path, check_same_thread=False)
                self._conn.execute(_CREATE_TABLE)
                self._conn.execute(_CREATE_INDEX)
                self._conn.commit()
            except sqlite3.Error as inner_exc:
                raise CacheError(f"Failed to create cache database: {inner_exc}") from inner_exc

    def get(self, file_path: str, content_hash: str) -> FileInfo | None:
        if self._closed:
            raise CacheError("Cache is closed")
        with self._lock:
            try:
                cur = self._conn.execute(
                    "SELECT path, content_hash, language, lines, symbols_json, "
                    "references_json, indexed_at FROM files WHERE path = ?",
                    (file_path,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                if row[1] != content_hash:
                    return None
                return _row_to_fileinfo(row)
            except sqlite3.Error as exc:
                raise CacheError(f"Failed to read cache for {file_path}: {exc}") from exc

    def put(self, file_info: FileInfo) -> None:
        if self._closed:
            raise CacheError("Cache is closed")
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO files"
                    " (path, content_hash, language, lines,"
                    " symbols_json, references_json, indexed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        file_info.path,
                        file_info.content_hash,
                        file_info.language,
                        file_info.lines,
                        _serialize_symbols(file_info.symbols),
                        _serialize_references(file_info.references),
                        time.time(),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                raise CacheError(f"Failed to write cache for {file_info.path}: {exc}") from exc

    def invalidate(self, file_path: str) -> None:
        if self._closed:
            raise CacheError("Cache is closed")
        with self._lock:
            try:
                self._conn.execute("DELETE FROM files WHERE path = ?", (file_path,))
                self._conn.commit()
            except sqlite3.Error as exc:
                raise CacheError(f"Failed to invalidate cache for {file_path}: {exc}") from exc

    def clear(self) -> None:
        if self._closed:
            raise CacheError("Cache is closed")
        with self._lock:
            try:
                self._conn.execute("DELETE FROM files")
                self._conn.commit()
            except sqlite3.Error as exc:
                raise CacheError(f"Failed to clear cache: {exc}") from exc

    def get_all(self) -> dict[str, FileInfo]:
        if self._closed:
            raise CacheError("Cache is closed")
        with self._lock:
            try:
                cur = self._conn.execute(
                    "SELECT path, content_hash, language, lines, symbols_json, "
                    "references_json, indexed_at FROM files"
                )
                return {row[0]: _row_to_fileinfo(row) for row in cur.fetchall()}
            except sqlite3.Error as exc:
                raise CacheError(f"Failed to read all cache entries: {exc}") from exc

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            self._conn.close()
            self._closed = True

    def __enter__(self) -> IndexCache:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
