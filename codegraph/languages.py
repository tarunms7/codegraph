"""Language detection and tree-sitter grammar loading."""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path

import tree_sitter

logger = logging.getLogger("codegraph")

SUPPORTED_LANGUAGES: dict[str, list[str]] = {
    "python": [".py", ".pyi"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "go": [".go"],
    "rust": [".rs"],
    "java": [".java"],
}

# Reverse lookup: extension -> language name
_EXTENSION_MAP: dict[str, str] = {}
for _lang, _exts in SUPPORTED_LANGUAGES.items():
    for _ext in _exts:
        _EXTENSION_MAP[_ext] = _lang

# Module-level caches
_parser_cache: dict[str, tree_sitter.Parser] = {}
_query_cache: dict[str, tree_sitter.Query | None] = {}

# Map from our language names to tree-sitter-language-pack names
_LANGUAGE_PACK_NAMES: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "javascript": "javascript",
    "go": "go",
    "rust": "rust",
    "java": "java",
}


def detect_language(file_path: str) -> str | None:
    """Detect programming language from file extension.

    Returns language name string or None if unsupported.
    """
    ext = Path(file_path).suffix.lower()
    return _EXTENSION_MAP.get(ext)


def get_parser(language: str) -> tree_sitter.Parser:
    """Get a configured tree-sitter parser for the given language.

    Parsers are cached at module level — same object returned for same language.

    Raises:
        ValueError: If language is not in SUPPORTED_LANGUAGES.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")

    if language in _parser_cache:
        return _parser_cache[language]

    from tree_sitter_language_pack import get_language

    pack_name = _LANGUAGE_PACK_NAMES[language]
    lang_obj = get_language(pack_name)

    parser = tree_sitter.Parser(lang_obj)
    _parser_cache[language] = parser
    logger.debug("Created parser for %s", language)
    return parser


def get_query(language: str) -> tree_sitter.Query | None:
    """Load and compile the tree-sitter query for the given language.

    Queries are loaded from .scm files via importlib.resources and cached.
    Returns None if the .scm file is missing.

    Raises:
        ValueError: If language is not in SUPPORTED_LANGUAGES.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")

    if language in _query_cache:
        return _query_cache[language]

    from tree_sitter_language_pack import get_language

    try:
        query_file = files("codegraph.queries").joinpath(f"{language}.scm")
        query_text = query_file.read_text(encoding="utf-8")
    except (FileNotFoundError, TypeError, OSError):
        logger.warning("No .scm query file found for %s", language)
        _query_cache[language] = None
        return None

    pack_name = _LANGUAGE_PACK_NAMES[language]
    lang_obj = get_language(pack_name)
    try:
        query = tree_sitter.Query(lang_obj, query_text)
    except Exception as exc:
        logger.warning("Failed to compile query for %s: %s", language, exc)
        _query_cache[language] = None
        return None
    _query_cache[language] = query
    logger.debug("Loaded query for %s", language)
    return query
