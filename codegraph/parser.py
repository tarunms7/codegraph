"""Tree-sitter parsing and symbol extraction."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import tree_sitter

from codegraph.languages import detect_language, get_parser, get_query
from codegraph.models import EdgeKind, FileInfo, Reference, Symbol, SymbolKind

logger = logging.getLogger("codegraph")

# Map capture name suffixes to SymbolKind
_DEFINITION_KIND_MAP: dict[str, SymbolKind] = {
    "function": SymbolKind.FUNCTION,
    "method": SymbolKind.METHOD,
    "class": SymbolKind.CLASS,
    "variable": SymbolKind.VARIABLE,
    "type": SymbolKind.TYPE,
    "interface": SymbolKind.INTERFACE,
    "enum": SymbolKind.ENUM,
}

# Map capture name suffixes to EdgeKind
_REFERENCE_KIND_MAP: dict[str, EdgeKind] = {
    "import": EdgeKind.IMPORTS,
    "inherit": EdgeKind.INHERITS,
    "implement": EdgeKind.IMPLEMENTS,
}

# Regex fallback patterns for import extraction when no .scm query available
_IMPORT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
        re.compile(r"^\s*from\s+([\w.]+)\s+import", re.MULTILINE),
    ],
    "typescript": [
        re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE),
    ],
    "javascript": [
        re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE),
        re.compile(
            r"""^\s*(?:const|let|var)\s+.*?=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
            re.MULTILINE,
        ),
    ],
    "go": [
        re.compile(r"""^\s*"([^"]+)"\s*$""", re.MULTILINE),
    ],
    "rust": [
        re.compile(r"^\s*use\s+([\w:]+)", re.MULTILINE),
    ],
    "java": [
        re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    ],
}


def _extract_signature(node: object, source_bytes: bytes) -> str:
    """Extract signature from a definition node.

    Per C8: get the parent (full definition) node, read source bytes for that range,
    take first line, strip trailing ':', '{', whitespace, truncate to 200 chars.
    """
    # The captured node is typically the identifier — walk up to the definition node
    def_node = node.parent if node.parent is not None else node

    start = def_node.start_byte
    end = def_node.end_byte
    text = source_bytes[start:end].decode("utf-8", errors="replace")

    # Take first line only
    first_line = text.split("\n", 1)[0]

    # Strip trailing ':', '{', and whitespace
    first_line = first_line.rstrip().rstrip(":{").rstrip()

    # Truncate to 200 chars
    if len(first_line) > 200:
        first_line = first_line[:197] + "..."

    return first_line



def _find_enclosing_class(node: object) -> str | None:
    """Walk up the AST to find the enclosing class name for a method."""
    current = node.parent
    while current is not None:
        if current.type in (
            "class_definition",  # Python
            "class_declaration",  # TS/JS/Java
            "impl_item",  # Rust
        ):
            # Find the name child
            for child in current.children:
                if child.type in ("identifier", "type_identifier"):
                    return child.text.decode("utf-8", errors="replace")
            break
        current = current.parent
    return None


def _clean_import_text(text: str, language: str) -> str:
    """Clean up import target text based on language conventions."""
    # Strip surrounding quotes (TS/JS string imports, Go interpreted_string_literal)
    if text and len(text) >= 2 and text[0] in ('"', "'", "`") and text[-1] in ('"', "'", "`"):
        text = text[1:-1]
    return text


def _extract_imports_regex(content: str, language: str, rel_path: str) -> list[Reference]:
    """Fallback: extract imports using regex when no .scm query available."""
    references: list[Reference] = []
    patterns = _IMPORT_PATTERNS.get(language, [])
    for pattern in patterns:
        for match in pattern.finditer(content):
            target = match.group(1)
            line = content[: match.start()].count("\n") + 1
            references.append(
                Reference(
                    source_file=rel_path,
                    target_name=target,
                    line=line,
                    kind=EdgeKind.IMPORTS,
                )
            )
    return references


def _extract_supplemental_refs(
    root_node: object,
    source_bytes: bytes,
    language: str,
    rel_path: str,
    existing_refs: list[Reference],
) -> None:
    """Extract references the .scm query may have missed (e.g., Python relative imports).

    Modifies existing_refs in place.
    """
    # Track existing ref lines+names to avoid duplicates
    existing = {(r.line, r.target_name) for r in existing_refs}

    if language == "python":
        # Walk tree for import_from_statement with relative_import
        _walk_python_relative_imports(root_node, source_bytes, rel_path, existing, existing_refs)


def _walk_python_relative_imports(
    node: object,
    source_bytes: bytes,
    rel_path: str,
    existing: set[tuple[int, str]],
    refs: list[Reference],
) -> None:
    """Walk AST to find Python relative imports (from .foo import bar)."""
    if node.type == "import_from_statement":
        # Check for relative_import child
        for child in node.children:
            if child.type == "relative_import":
                text = child.text.decode("utf-8", errors="replace")
                line = child.start_point[0] + 1
                if (line, text) not in existing:
                    refs.append(
                        Reference(
                            source_file=rel_path,
                            target_name=text,
                            line=line,
                            kind=EdgeKind.IMPORTS,
                        )
                    )
                    existing.add((line, text))
                return  # Don't recurse into children

    for child in node.children:
        _walk_python_relative_imports(child, source_bytes, rel_path, existing, refs)


def parse_file(file_path: str, repo_root: str) -> FileInfo:
    """Parse a single source file and extract symbols and references.

    Never raises — returns empty/partial FileInfo on errors.

    Args:
        file_path: Absolute path to the file to parse.
        repo_root: Absolute path to the repository root.

    Returns:
        FileInfo with extracted symbols, references, and metadata.
    """
    rel_path = os.path.relpath(file_path, repo_root)

    # Binary detection: read first 8KB
    try:
        with open(file_path, "rb") as f:
            head = f.read(8192)
    except OSError as e:
        logger.warning("Cannot read file %s: %s", rel_path, e)
        return FileInfo(path=rel_path, language="unknown", content_hash="")

    if b"\x00" in head:
        return FileInfo(path=rel_path, language="binary", content_hash="")

    # Read full content
    try:
        with open(file_path, "rb") as f:
            raw_bytes = f.read()
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Unicode decode error in %s, skipping", rel_path)
        return FileInfo(path=rel_path, language="unknown", content_hash="")
    except OSError as e:
        logger.warning("Cannot read file %s: %s", rel_path, e)
        return FileInfo(path=rel_path, language="unknown", content_hash="")

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    if not content:
        line_count = 0

    # Detect language
    language = detect_language(file_path)
    if language is None:
        return FileInfo(
            path=rel_path,
            language="unknown",
            content_hash=content_hash,
            lines=line_count,
        )

    # Get parser and parse
    try:
        parser = get_parser(language)
        tree = parser.parse(raw_bytes)
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", rel_path, e)
        return FileInfo(
            path=rel_path,
            language=language,
            content_hash=content_hash,
            lines=line_count,
        )

    # Get query
    query = get_query(language)
    if query is None:
        logger.warning("No .scm query for %s, falling back to regex imports", language)
        references = _extract_imports_regex(content, language, rel_path)
        return FileInfo(
            path=rel_path,
            language=language,
            content_hash=content_hash,
            references=references,
            lines=line_count,
        )

    # Run query matches
    symbols: list[Symbol] = []
    references: list[Reference] = []

    try:
        cursor = tree_sitter.QueryCursor(query)
        matches = cursor.matches(tree.root_node)
    except Exception as e:
        logger.warning("Query execution failed for %s: %s", rel_path, e)
        return FileInfo(
            path=rel_path,
            language=language,
            content_hash=content_hash,
            lines=line_count,
        )

    for _pattern_idx, capture_dict in matches:
        for capture_name, nodes in capture_dict.items():
            # nodes can be a list of nodes
            if not isinstance(nodes, list):
                nodes = [nodes]

            for node in nodes:
                # Parse capture name: name.definition.{kind} or name.reference.{kind}
                parts = capture_name.split(".")
                if len(parts) != 3 or parts[0] != "name":
                    continue

                category = parts[1]  # "definition" or "reference"
                kind_suffix = parts[2]  # "function", "method", "import", etc.

                node_text = node.text.decode("utf-8", errors="replace")
                node_line = node.start_point[0] + 1  # 0-indexed -> 1-indexed

                if category == "definition":
                    sym_kind = _DEFINITION_KIND_MAP.get(kind_suffix)
                    if sym_kind is None:
                        continue

                    signature = _extract_signature(node, raw_bytes)

                    # Find end_line from the definition node (parent of identifier)
                    def_node = node.parent if node.parent is not None else node
                    end_line = def_node.end_point[0] + 1  # 0-indexed -> 1-indexed

                    # For methods, find enclosing class
                    parent_class = None
                    if sym_kind == SymbolKind.METHOD:
                        parent_class = _find_enclosing_class(node)

                    symbols.append(
                        Symbol(
                            name=node_text,
                            kind=sym_kind,
                            file=rel_path,
                            line=node_line,
                            signature=signature,
                            parent=parent_class,
                            end_line=end_line,
                        )
                    )

                elif category == "reference":
                    ref_kind = _REFERENCE_KIND_MAP.get(kind_suffix)
                    if ref_kind is None:
                        continue

                    target_name = _clean_import_text(node_text, language)

                    references.append(
                        Reference(
                            source_file=rel_path,
                            target_name=target_name,
                            line=node_line,
                            kind=ref_kind,
                        )
                    )

    # Supplement: extract references the .scm query may have missed (e.g., Python relative imports)
    _extract_supplemental_refs(tree.root_node, raw_bytes, language, rel_path, references)

    # Deduplicate: if a symbol appears as both function and method at the same line,
    # keep only the method version (more specific).
    method_lines = {s.line for s in symbols if s.kind == SymbolKind.METHOD}
    symbols = [s for s in symbols if not (s.kind == SymbolKind.FUNCTION and s.line in method_lines)]

    return FileInfo(
        path=rel_path,
        language=language,
        content_hash=content_hash,
        symbols=symbols,
        references=references,
        lines=line_count,
    )


def parse_files(file_paths: list[str], repo_root: str) -> dict[str, FileInfo]:
    """Parse multiple files in parallel using ThreadPoolExecutor.

    Args:
        file_paths: List of absolute file paths to parse.
        repo_root: Absolute path to the repository root.

    Returns:
        Dict mapping relative path -> FileInfo.
    """
    results: dict[str, FileInfo] = {}

    if not file_paths:
        return results

    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(parse_file, fp, repo_root): fp for fp in file_paths}
        for future in as_completed(futures):
            fp = futures[future]
            try:
                info = future.result()
                results[info.path] = info
            except Exception as e:
                rel = os.path.relpath(fp, repo_root)
                logger.warning("Failed to parse %s: %s", rel, e)

    return results
