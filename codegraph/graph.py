"""Dependency graph builder — resolves references and constructs a NetworkX MultiDiGraph."""

from __future__ import annotations

import logging
import posixpath
from pathlib import PurePosixPath

import networkx as nx

from codegraph.models import EdgeKind, FileInfo, Reference

logger = logging.getLogger("codegraph")


def build_graph(files: dict[str, FileInfo]) -> nx.MultiDiGraph:
    """Build a dependency MultiDiGraph from parsed file metadata.

    Nodes are file paths with ``file_info`` attributes.
    Edges carry ``kind`` (:class:`EdgeKind`) and ``symbols`` (list of symbol names).
    """
    graph = nx.MultiDiGraph()

    for path, file_info in files.items():
        graph.add_node(path, file_info=file_info)

    resolved = resolve_references(files)

    for ref in resolved:
        if ref.source_file == ref.target_file:
            continue  # no self-loops
        _add_or_merge_edge(graph, ref.source_file, ref.target_file, ref.kind, ref.target_name)

    _detect_test_edges(files, graph)

    logger.debug(
        "Graph built: %d nodes, %d edges", graph.number_of_nodes(), graph.number_of_edges()
    )
    return graph


def resolve_references(files: dict[str, FileInfo]) -> list[Reference]:
    """Resolve unresolved references to concrete file paths."""
    # Build symbol lookup: {symbol_name: [file_paths]}
    symbol_lookup: dict[str, list[str]] = {}
    for path, fi in files.items():
        for sym in fi.symbols:
            symbol_lookup.setdefault(sym.name, []).append(path)

    all_paths = set(files.keys())
    resolved: list[Reference] = []

    for path, fi in files.items():
        for ref in fi.references:
            if ref.target_file is not None:
                resolved.append(ref)
                continue

            targets = _resolve_single(ref, path, fi.language, all_paths, symbol_lookup)
            for t in targets:
                resolved.append(
                    Reference(
                        source_file=ref.source_file,
                        target_name=ref.target_name,
                        target_file=t,
                        line=ref.line,
                        kind=ref.kind,
                    )
                )

    return resolved


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _add_or_merge_edge(
    graph: nx.MultiDiGraph,
    src: str,
    tgt: str,
    kind: EdgeKind,
    symbol_name: str,
) -> None:
    """Add an edge or merge symbols into an existing edge of the same kind."""
    # Check existing edges between src and tgt
    if graph.has_edge(src, tgt):
        for _key, data in graph[src][tgt].items():
            if data.get("kind") == kind:
                syms: list[str] = data["symbols"]
                if symbol_name not in syms:
                    syms.append(symbol_name)
                return
    graph.add_edge(src, tgt, kind=kind, symbols=[symbol_name])


def _resolve_single(
    ref: Reference,
    source_path: str,
    language: str,
    all_paths: set[str],
    symbol_lookup: dict[str, list[str]],
) -> list[str]:
    """Resolve a single reference to zero or more target file paths."""
    target_name = ref.target_name

    if language == "python":
        return _resolve_python(target_name, source_path, all_paths, symbol_lookup)
    if language in ("typescript", "javascript"):
        return _resolve_ts_js(target_name, source_path, all_paths, symbol_lookup)
    if language == "go":
        return _resolve_go(target_name, all_paths)
    if language == "rust":
        return _resolve_rust(target_name, source_path, all_paths, symbol_lookup)
    if language == "java":
        return _resolve_java(target_name, all_paths, symbol_lookup)

    # Fallback: try symbol lookup
    return _resolve_by_symbol(target_name, source_path, all_paths, symbol_lookup)


def _resolve_python(
    target_name: str,
    source_path: str,
    all_paths: set[str],
    symbol_lookup: dict[str, list[str]],
) -> list[str]:
    """Resolve a Python import reference."""
    source_dir = str(PurePosixPath(source_path).parent)

    # Relative import (starts with .)
    if target_name.startswith("."):
        return _resolve_python_relative(target_name, source_dir, all_paths)

    # Absolute import: from foo.bar import baz  →  target_name might be "foo.bar" or "baz"
    parts = target_name.replace(".", "/")

    # Try as module path: foo.bar → foo/bar.py or foo/bar/__init__.py
    candidates = [
        f"{parts}.py",
        f"{parts}/__init__.py",
    ]
    # Also try in same directory
    basename = target_name.rsplit(".", 1)[-1]
    same_dir = f"{source_dir}/{basename}.py" if source_dir != "." else f"{basename}.py"
    candidates.insert(0, same_dir)

    # Try same dir __init__
    same_dir_pkg = (
        f"{source_dir}/{basename}/__init__.py" if source_dir != "." else f"{basename}/__init__.py"
    )
    candidates.append(same_dir_pkg)

    for c in candidates:
        normalized = _normalize_path(c)
        if normalized in all_paths:
            return [normalized]

    # Fall back to symbol lookup
    return _resolve_by_symbol(basename, source_path, all_paths, symbol_lookup)


def _resolve_python_relative(target_name: str, source_dir: str, all_paths: set[str]) -> list[str]:
    """Resolve a Python relative import like '.models' or '..auth'."""
    # Count leading dots
    dots = 0
    for ch in target_name:
        if ch == ".":
            dots += 1
        else:
            break
    remainder = target_name[dots:]

    # Navigate up (dots-1) directories from source_dir
    base = PurePosixPath(source_dir)
    for _ in range(dots - 1):
        base = base.parent

    if remainder:
        parts = remainder.replace(".", "/")
        candidates = [
            str(base / f"{parts}.py"),
            str(base / parts / "__init__.py"),
        ]
    else:
        candidates = [str(base / "__init__.py")]

    for c in candidates:
        normalized = _normalize_path(c)
        if normalized in all_paths:
            return [normalized]
    return []


def _resolve_ts_js(
    target_name: str,
    source_path: str,
    all_paths: set[str],
    symbol_lookup: dict[str, list[str]],
) -> list[str]:
    """Resolve a TypeScript/JavaScript import."""
    # Non-relative imports are external packages
    if not target_name.startswith(".") and not target_name.startswith("/"):
        return []

    source_dir = str(PurePosixPath(source_path).parent)
    base = str(PurePosixPath(source_dir) / target_name)

    extensions = [".ts", ".tsx", ".js", ".jsx"]
    candidates = []
    for ext in extensions:
        candidates.append(f"{base}{ext}")
    candidates.append(f"{base}/index.ts")
    candidates.append(f"{base}/index.js")

    for c in candidates:
        normalized = _normalize_path(c)
        if normalized in all_paths:
            return [normalized]
    return []


def _resolve_go(target_name: str, all_paths: set[str]) -> list[str]:
    """Resolve a Go import by matching path suffix against repo dirs."""
    # Match import path suffix against directory structure
    for path in all_paths:
        dir_path = str(PurePosixPath(path).parent)
        if dir_path == target_name or dir_path.endswith(f"/{target_name}"):
            return [path]
    return []


def _resolve_rust(
    target_name: str,
    source_path: str,
    all_paths: set[str],
    symbol_lookup: dict[str, list[str]],
) -> list[str]:
    """Resolve a Rust use path."""
    if target_name.startswith("crate::"):
        # crate::module::Item → src/module.rs or src/module/mod.rs
        parts = target_name.removeprefix("crate::").split("::")
        module_parts = parts[:-1] if len(parts) > 1 else parts
        module_path = "/".join(module_parts)
        candidates = [
            f"src/{module_path}.rs",
            f"src/{module_path}/mod.rs",
        ]
        for c in candidates:
            if c in all_paths:
                return [c]
    elif target_name.startswith("super::"):
        source_dir = str(PurePosixPath(source_path).parent)
        parts = target_name.removeprefix("super::").split("::")
        module = parts[0]
        parent = str(PurePosixPath(source_dir).parent)
        candidates = [
            f"{parent}/{module}.rs",
            f"{parent}/{module}/mod.rs",
        ]
        for c in candidates:
            normalized = _normalize_path(c)
            if normalized in all_paths:
                return [normalized]
    # External crate
    return _resolve_by_symbol(target_name.split("::")[-1], source_path, all_paths, symbol_lookup)


def _resolve_java(
    target_name: str,
    all_paths: set[str],
    symbol_lookup: dict[str, list[str]],
) -> list[str]:
    """Resolve a Java import."""
    # import com.example.Foo → com/example/Foo.java
    path_from_import = target_name.replace(".", "/") + ".java"
    if path_from_import in all_paths:
        return [path_from_import]

    # Try matching just the class name
    class_name = target_name.rsplit(".", 1)[-1]
    for p in all_paths:
        if p.endswith(f"/{class_name}.java") or p == f"{class_name}.java":
            return [p]

    # Wildcard: com.example.* → com/example/ directory
    if target_name.endswith(".*"):
        dir_prefix = target_name[:-2].replace(".", "/")
        matches = [p for p in all_paths if p.startswith(dir_prefix + "/") and p.endswith(".java")]
        if matches:
            return matches

    return _resolve_by_symbol(class_name, "", all_paths, symbol_lookup)


def _resolve_by_symbol(
    symbol_name: str,
    source_path: str,
    all_paths: set[str],
    symbol_lookup: dict[str, list[str]],
) -> list[str]:
    """Resolve by symbol name lookup with C7 collision resolution."""
    candidates = symbol_lookup.get(symbol_name, [])
    if not candidates:
        return []
    if len(candidates) == 1:
        return candidates

    # C7: prefer same directory
    source_dir = str(PurePosixPath(source_path).parent) if source_path else ""
    same_dir = [c for c in candidates if str(PurePosixPath(c).parent) == source_dir]
    if len(same_dir) == 1:
        return same_dir

    # C7: prefer same top-level package
    if source_path:
        source_top = source_path.split("/")[0] if "/" in source_path else ""
        same_pkg = [c for c in candidates if (c.split("/")[0] if "/" in c else "") == source_top]
        if len(same_pkg) == 1:
            return same_pkg

    # C7: still ambiguous — return all (create Reference per target)
    return list(candidates)


def _detect_test_edges(files: dict[str, FileInfo], graph: nx.MultiDiGraph) -> None:
    """Detect test files and add TESTS edges to matching source files."""
    all_paths = set(files.keys())

    for path, fi in files.items():
        stem = _get_test_stem(path, fi.language)
        if stem is None:
            continue

        source_file = _find_source_for_test(stem, path, fi.language, all_paths)
        if source_file and source_file != path:
            _add_or_merge_edge(graph, path, source_file, EdgeKind.TESTS, f"test:{stem}")


def _get_test_stem(path: str, language: str) -> str | None:
    """Extract the test stem from a test file path, or None if not a test file."""
    basename = PurePosixPath(path).stem  # filename without extension
    dir_parts = PurePosixPath(path).parts

    if language == "python":
        if basename.startswith("test_"):
            return basename[5:]
        if basename.endswith("_test"):
            return basename[:-5]
    elif language in ("typescript", "javascript"):
        # file.test.ts, file.spec.ts
        if ".test." in PurePosixPath(path).name or ".spec." in PurePosixPath(path).name:
            return basename.removesuffix(".test").removesuffix(".spec")
        # __tests__/ directory
        if "__tests__" in dir_parts:
            # Strip .test or .spec suffix if present
            stem = basename.removesuffix(".test").removesuffix(".spec")
            return stem
    elif language == "go":
        if basename.endswith("_test"):
            return basename[:-5]
    elif language == "java":
        if basename.endswith("Test"):
            return basename[:-4]

    return None


def _find_source_for_test(
    stem: str, test_path: str, language: str, all_paths: set[str]
) -> str | None:
    """Find the source file that a test file tests."""
    test_dir = str(PurePosixPath(test_path).parent)

    # Determine possible extensions
    ext_map: dict[str, list[str]] = {
        "python": [".py"],
        "typescript": [".ts", ".tsx"],
        "javascript": [".js", ".jsx"],
        "go": [".go"],
        "java": [".java"],
    }
    extensions = ext_map.get(language, [".py", ".ts", ".js"])

    candidates: list[tuple[str, int]] = []  # (path, distance)

    for p in all_paths:
        p_stem = PurePosixPath(p).stem
        if p_stem != stem:
            continue
        if p == test_path:
            continue
        # Check extension matches
        if not any(p.endswith(ext) for ext in extensions):
            continue
        # Calculate directory distance
        dist = _dir_distance(test_dir, str(PurePosixPath(p).parent))
        candidates.append((p, dist))

    if not candidates:
        # C19: check parallel source directories (tests/ → src/, lib/, app/)
        return _check_parallel_dirs(stem, test_path, language, all_paths, extensions)

    # Prefer closest in directory structure
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def _check_parallel_dirs(
    stem: str,
    test_path: str,
    language: str,
    all_paths: set[str],
    extensions: list[str],
) -> str | None:
    """Check parallel source directories for a matching file."""
    parts = PurePosixPath(test_path).parts
    source_dirs = ["src", "lib", "app"]

    for i, part in enumerate(parts):
        if part in ("tests", "__tests__", "test"):
            for src_dir in source_dirs:
                new_parts = list(parts[:i]) + [src_dir] + list(parts[i + 1 :])
                # Replace the test filename with source filename
                for ext in extensions:
                    source_parts = new_parts[:-1]
                    source_name = stem + ext
                    candidate = (
                        str(PurePosixPath(*source_parts, source_name))
                        if source_parts
                        else source_name
                    )
                    candidate = _normalize_path(candidate)
                    if candidate in all_paths:
                        return candidate
            # Also try one level up from tests/
            parent_parts = list(parts[:i])
            for ext in extensions:
                candidate = (
                    str(PurePosixPath(*parent_parts, stem + ext)) if parent_parts else stem + ext
                )
                candidate = _normalize_path(candidate)
                if candidate in all_paths:
                    return candidate
    return None


def _dir_distance(dir_a: str, dir_b: str) -> int:
    """Rough directory distance — number of differing path components."""
    parts_a = PurePosixPath(dir_a).parts
    parts_b = PurePosixPath(dir_b).parts
    # Find common prefix length
    common = 0
    for a, b in zip(parts_a, parts_b, strict=False):
        if a == b:
            common += 1
        else:
            break
    return (len(parts_a) - common) + (len(parts_b) - common)


def _normalize_path(path: str) -> str:
    """Normalize a path: resolve '..' and '.', remove leading './'."""
    return str(PurePosixPath(posixpath.normpath(path)))
