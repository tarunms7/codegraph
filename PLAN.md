# codegraph — Implementation Plan

## What This Is

A standalone Python library that takes a codebase and produces ranked, token-budget-aware context for LLMs and AI agents. No external services, no embedding APIs, no GPU. Pure local computation.

```
pip install codegraph
```

```python
from codegraph import CodeGraph

cg = CodeGraph("/path/to/repo")

# For agent orchestrators — context for specific files an agent will edit
context = cg.context_for(
    files=["src/auth.py", "src/middleware.py"],
    token_budget=4096,
)

# For chat tools — context for a natural language query (keyword-based, no embeddings)
context = cg.query("authentication middleware", token_budget=4096)

# For Aider-style tools — full repo map
map_text = cg.repo_map(token_budget=2048)

# Refresh (only re-parses changed files)
cg.refresh()

# Raw graph access for custom use
graph = cg.graph        # NetworkX DiGraph
symbols = cg.symbols    # dict[str, list[Symbol]]
```

That is the entire public API. Three methods that return strings. One refresh method. Two properties for advanced users.

---

## Core Principles

1. **Accuracy is non-negotiable.** Wrong context is proven worse than no context (SWE-ContextBench 2025). Every symbol, every edge, every ranking must be correct. If we are not sure, we omit — never guess.

2. **Token budget is sacred.** If you say 4096 tokens, you get ≤4096 tokens. The most important symbols come first. Context rot research proves that overstuffing degrades LLM performance. We respect the budget.

3. **Zero friction.** `pip install codegraph`, three lines of code, you have context. No config files, no setup, no external services. It just works.

4. **Incremental by default.** First index of a 500-file repo: <3 seconds. Subsequent updates: milliseconds. We hash files and only re-parse what changed.

5. **No external dependencies beyond Python packages.** No embedding APIs, no vector databases, no Docker, no GPU. The library works on any machine with Python 3.10+.

6. **Tested exhaustively.** Every public method has tests. Every edge case (empty files, syntax errors, circular imports, binary files, massive repos) is covered. No "it works on my machine."

---

## Architecture

```
codegraph/
├── __init__.py            # Public API: CodeGraph class
├── models.py              # Data models: Symbol, FileInfo, Reference
├── parser.py              # Tree-sitter parsing → symbol extraction
├── languages.py           # Language detection + grammar loading
├── graph.py               # Dependency graph builder (NetworkX)
├── ranker.py              # PageRank with task-aware personalization
├── renderer.py            # Token-budget-aware context rendering
├── cache.py               # SQLite cache with content-hash invalidation
├── cli.py                 # CLI: `codegraph map /path/to/repo`
├── py.typed               # PEP 561 type marker
└── queries/               # Tree-sitter query files per language
    ├── python.scm
    ├── typescript.scm
    ├── javascript.scm
    ├── go.scm
    ├── rust.scm
    ├── java.scm
    ├── c.scm
    ├── cpp.scm
    ├── ruby.scm
    ├── csharp.scm
    ├── swift.scm
    ├── kotlin.scm
    └── php.scm

tests/
├── conftest.py            # Shared fixtures
├── test_parser.py         # Symbol extraction tests
├── test_graph.py          # Graph building tests
├── test_ranker.py         # Ranking tests
├── test_renderer.py       # Rendering + token budget tests
├── test_cache.py          # Cache correctness tests
├── test_codegraph.py      # Integration tests for CodeGraph class
├── test_cli.py            # CLI tests
├── test_languages.py      # Language detection tests
└── fixtures/              # Real code samples for testing
    ├── python_project/
    │   ├── app.py
    │   ├── auth.py
    │   ├── models.py
    │   ├── utils.py
    │   └── tests/
    │       └── test_auth.py
    ├── typescript_project/
    │   ├── index.ts
    │   ├── auth.ts
    │   ├── types.ts
    │   └── __tests__/
    │       └── auth.test.ts
    ├── mixed_project/       # Python + TypeScript in one repo
    │   ├── backend/
    │   │   ├── main.py
    │   │   └── models.py
    │   └── frontend/
    │       ├── App.tsx
    │       └── api.ts
    ├── edge_cases/
    │   ├── empty_file.py
    │   ├── syntax_error.py
    │   ├── binary_file.bin
    │   ├── circular_a.py    # imports circular_b
    │   ├── circular_b.py    # imports circular_a
    │   ├── large_file.py    # 1000+ lines
    │   └── no_symbols.txt
    └── single_file/
        └── hello.py
```

---

## Data Models (`models.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum

class SymbolKind(StrEnum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    TYPE = "type"
    INTERFACE = "interface"
    ENUM = "enum"
    CONSTANT = "constant"
    MODULE = "module"

class EdgeKind(StrEnum):
    IMPORTS = "imports"         # file A imports from file B
    CALLS = "calls"            # file A calls a function in file B
    INHERITS = "inherits"      # class in A extends class in B
    IMPLEMENTS = "implements"  # class in A implements interface in B
    TESTS = "tests"            # file A is a test for file B
    USES_TYPE = "uses_type"    # file A uses a type defined in B

@dataclass(frozen=True, slots=True)
class Symbol:
    """A named code symbol extracted from a source file."""
    name: str
    kind: SymbolKind
    file: str            # relative path from repo root
    line: int            # 1-indexed line number
    signature: str       # full signature (e.g., "def authenticate(token: str) -> User")
    parent: str | None = None  # enclosing class/module (None for top-level)
    end_line: int | None = None  # end line of the symbol block

@dataclass(frozen=True, slots=True)
class Reference:
    """A reference from one file to a symbol in another file."""
    source_file: str     # file containing the reference
    target_name: str     # symbol name being referenced
    target_file: str | None = None  # resolved target file (None if unresolved)
    line: int = 0        # line where the reference occurs
    kind: EdgeKind = EdgeKind.IMPORTS

@dataclass(slots=True)
class FileInfo:
    """Parsed metadata about a single source file."""
    path: str            # relative path from repo root
    language: str        # detected language name
    content_hash: str    # SHA-256 hex digest of file content
    symbols: list[Symbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    lines: int = 0       # total line count
```

---

## Module Specifications

### 1. `languages.py` — Language Detection + Grammar Loading

**Responsibility**: Map file extensions to tree-sitter languages. Load the correct grammar for parsing.

**Key functions**:
- `detect_language(file_path: str) -> str | None` — returns language name or None if unsupported
- `get_parser(language: str) -> tree_sitter.Parser` — returns a configured parser for the language
- `get_query(language: str) -> tree_sitter.Query | None` — returns the tag extraction query for the language
- `SUPPORTED_LANGUAGES: dict[str, list[str]]` — mapping of language name to file extensions

**Supported languages at launch** (13 languages):
```
python:      [.py, .pyi]
typescript:  [.ts, .tsx]
javascript:  [.js, .jsx, .mjs, .cjs]
go:          [.go]
rust:        [.rs]
java:        [.java]
c:           [.c, .h]
cpp:         [.cpp, .cc, .cxx, .hpp, .hxx]
ruby:        [.rb]
csharp:      [.cs]
swift:       [.swift]
kotlin:      [.kt, .kts]
php:         [.php]
```

**Implementation notes**:
- Use `tree-sitter-language-pack` (NOT the unmaintained `tree-sitter-languages`)
- Cache parsers — create once per language, reuse across files
- Gracefully return None for unsupported files (never crash)

### 2. `parser.py` — Tree-Sitter Parsing → Symbol Extraction

**Responsibility**: Parse source files and extract all symbols (definitions) and references (imports, calls, type usage).

**Key functions**:
- `parse_file(file_path: str, repo_root: str) -> FileInfo` — parse a single file, return extracted symbols and references
- `parse_files(file_paths: list[str], repo_root: str) -> dict[str, FileInfo]` — parse multiple files (can be parallelized with ThreadPoolExecutor)

**How symbol extraction works**:
1. Read the file content
2. Detect language via `languages.detect_language()`
3. Parse with tree-sitter to get AST
4. Run the language-specific `.scm` query to extract tagged nodes
5. For each definition node: create a `Symbol` with name, kind, line, and signature
6. For each import/reference node: create a `Reference`
7. Compute SHA-256 content hash
8. Return `FileInfo`

**Signature extraction rules**:
- For functions/methods: include the full signature line (name + params + return type)
- For classes: include the class line (name + bases/interfaces)
- For variables/constants: include the assignment line (name + type annotation if present)
- Signature is always a single line, max 200 chars (truncate with ... if longer)

**Reference extraction — what to capture per language**:

Python:
- `import foo` → Reference(target_name="foo", kind=IMPORTS)
- `from foo import bar` → Reference(target_name="foo", kind=IMPORTS)
- `class X(Base):` → Reference(target_name="Base", kind=INHERITS)

TypeScript/JavaScript:
- `import { X } from './auth'` → Reference(target_name="./auth", kind=IMPORTS)
- `class X extends Base` → Reference(target_name="Base", kind=INHERITS)
- `class X implements IFoo` → Reference(target_name="IFoo", kind=IMPLEMENTS)

Go:
- `import "package/name"` → Reference(target_name="package/name", kind=IMPORTS)

(Similar patterns for each language — extract imports and inheritance)

**Error handling**:
- If a file cannot be read (permissions, encoding): skip it, log warning, return empty FileInfo
- If tree-sitter fails to parse (syntax error): still return partial results from whatever parsed successfully
- If a .scm query file is missing for a language: fall back to regex-based extraction for imports only
- Binary files: detect via null bytes in first 8KB, skip entirely

### 3. `graph.py` — Dependency Graph Builder

**Responsibility**: Build a NetworkX DiGraph from parsed FileInfo objects. Nodes are files, edges are relationships.

**Key functions**:
- `build_graph(files: dict[str, FileInfo]) -> nx.DiGraph` — build the full dependency graph
- `resolve_references(files: dict[str, FileInfo]) -> list[Reference]` — resolve target_name references to actual file paths

**Reference resolution algorithm**:
1. Build a symbol lookup: `{symbol_name: file_path}` across all files
2. For each unresolved Reference in each file:
   a. If target_name is a relative path (starts with `.` or `/`): resolve to file path directly
   b. If target_name matches a symbol name in the lookup: resolve to that file
   c. If target_name matches a module/package name (directory with __init__.py): resolve to that
   d. If unresolvable: skip (external dependency — not in repo)
3. Deduplicate edges: if file A imports file B multiple times, create one edge with kind=IMPORTS

**Test file detection** (separate from tree-sitter — pattern matching):
For each file, check if it's a test file AND find what it tests:
- Python: `test_*.py` or `*_test.py` → tests the file with matching name (e.g., `test_auth.py` → `auth.py`)
- TypeScript/JS: `*.test.ts`, `*.spec.ts`, `__tests__/*.ts` → tests the matching source file
- Go: `*_test.go` → tests the `*.go` file in same directory
- Java: `*Test.java` → tests the matching class
- Create edges with kind=TESTS

**Graph properties**:
- Node attributes: `file_info: FileInfo` (the parsed metadata)
- Edge attributes: `kind: EdgeKind`, `symbols: list[str]` (which symbols create this edge)
- Self-loops are not allowed
- Parallel edges with different kinds ARE allowed (file A both imports and inherits from file B)

### 4. `ranker.py` — PageRank with Task-Aware Personalization

**Responsibility**: Rank files by importance, with optional bias toward specific task-relevant files.

**Key functions**:
- `rank_files(graph: nx.DiGraph, personalization: dict[str, float] | None = None, alpha: float = 0.85) -> dict[str, float]` — returns file paths ranked by score (higher = more important)
- `personalization_for_files(files: list[str], graph: nx.DiGraph) -> dict[str, float]` — create personalization vector biased toward specific files
- `personalization_for_query(query: str, graph: nx.DiGraph) -> dict[str, float]` — create personalization vector biased toward files matching query keywords

**How ranking works**:

Global ranking (no personalization — for `repo_map()`):
- Standard PageRank on the dependency graph
- Files that are imported by many other files rank higher
- Alpha=0.85 (standard damping factor)

Task-aware ranking (personalization — for `context_for()`):
1. Create personalization vector: task files get weight 1.0, all others get 0.0
2. Run PageRank with personalization vector
3. Result: files close to task files in the dependency graph rank highest
4. Distance-1 neighbors (direct imports, direct importers, test files) rank high
5. Distance-2+ files rank lower but still appear if they're structurally important

Query-based ranking (for `query()`):
1. Tokenize query into keywords
2. For each keyword, find files whose path or symbol names contain it (case-insensitive substring match)
3. Create personalization vector: matched files get weight proportional to match count
4. Run PageRank with this vector

**Edge case handling**:
- Disconnected graph (isolated files): isolated files get minimum rank, never zero
- Empty graph: return empty dict
- Single file: return {file: 1.0}

### 5. `renderer.py` — Token-Budget-Aware Context Rendering

**Responsibility**: Given ranked files and a token budget, produce a formatted context string that fits within the budget.

**Key functions**:
- `render_context(ranked_files: list[tuple[str, float]], file_infos: dict[str, FileInfo], token_budget: int, format: str = "markdown") -> str` — render context to fit within token budget
- `count_tokens(text: str) -> int` — count tokens using tiktoken (cl100k_base encoding)

**Rendering algorithm**:

1. Sort files by rank (highest first)
2. Partition into tiers:
   - **Tier 1** (top 30% by rank): Full detail — file path, all class/function signatures with params and return types
   - **Tier 2** (next 30%): Medium detail — file path, class names, function names (no full signatures)
   - **Tier 3** (next 20%): Minimal — file path + one-line summary (first docstring or first comment)
   - **Tier 4** (bottom 20%): Omitted entirely
3. Render Tier 1 first, count tokens
4. If budget remains, render Tier 2, count tokens
5. If budget remains, render Tier 3, count tokens
6. Stop as soon as adding the next item would exceed budget
7. If even Tier 1 exceeds budget: progressively drop symbols from lowest-ranked Tier 1 files

**Output format — Markdown** (default):
```markdown
## Relevant Context

### forge/api/routes/webhooks.py
> Handles GitHub webhook events for push, PR, and issue triggers.

```python
class WebhookHandler:
    async def handle_push_event(self, payload: dict) -> Response
    async def handle_pr_event(self, payload: dict) -> Response
    async def verify_signature(self, body: bytes, sig: str) -> bool
`` `

### forge/core/ci_watcher.py
> CI check monitoring and auto-fix loop.

```python
@dataclass
class CICheck:
    name: str
    status: str
    conclusion: str
    run_id: str

class CIFixLoop:
    async def poll_checks(self, pr_url: str) -> list[CICheck]
    async def fix_failure(self, check: CICheck) -> CIFixAttempt
`` `

### Related files
- `forge/core/daemon_helpers.py` — Git operations, subprocess management
- `forge/config/project_config.py` — CIFixConfig, project settings
```

**Output format — JSON** (for programmatic use):
```json
{
  "files": [
    {
      "path": "forge/api/routes/webhooks.py",
      "rank": 0.85,
      "tier": 1,
      "symbols": [
        {"name": "WebhookHandler", "kind": "class", "signature": "class WebhookHandler:", "line": 15},
        {"name": "handle_push_event", "kind": "method", "signature": "async def handle_push_event(self, payload: dict) -> Response", "line": 22}
      ]
    }
  ],
  "token_count": 3847,
  "token_budget": 4096,
  "files_included": 8,
  "files_total": 270
}
```

**Token counting**:
- Use tiktoken with cl100k_base encoding (GPT-4/Claude tokenizer approximation)
- Count tokens for the rendered output, not the raw source
- Include markdown formatting in the count (headers, code blocks, bullets)

### 6. `cache.py` — SQLite Persistent Cache

**Responsibility**: Cache parsed file metadata to avoid re-parsing unchanged files. Invalidate by content hash.

**Key functions**:
- `IndexCache(cache_dir: str)` — SQLite-backed cache stored at `{repo_root}/.codegraph/index.db`
- `cache.get(file_path: str, content_hash: str) -> FileInfo | None` — returns cached FileInfo if hash matches
- `cache.put(file_info: FileInfo) -> None` — store parsed result
- `cache.invalidate(file_path: str) -> None` — remove entry for a file
- `cache.clear() -> None` — delete entire cache
- `cache.get_all() -> dict[str, FileInfo]` — return all cached entries

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    language TEXT NOT NULL,
    lines INTEGER NOT NULL,
    symbols_json TEXT NOT NULL,    -- JSON serialized list[Symbol]
    references_json TEXT NOT NULL, -- JSON serialized list[Reference]
    indexed_at REAL NOT NULL       -- time.time()
);

CREATE INDEX IF NOT EXISTS idx_content_hash ON files(content_hash);
```

**Incremental update flow**:
1. `git ls-files` to get all tracked files (respects .gitignore)
2. For each file: compute SHA-256 of content
3. Check cache: if hash matches stored hash → skip (use cached FileInfo)
4. If hash differs or not in cache → parse the file, store in cache
5. Remove cache entries for files that no longer exist
6. This makes the second and subsequent calls near-instant

**Important**: The cache directory `.codegraph/` should be added to `.gitignore` by default. The library should print a one-time message suggesting this if the directory is created inside a git repo.

### 7. `__init__.py` — Public API: CodeGraph Class

**Responsibility**: The single entry point users interact with. Orchestrates all other modules.

```python
class CodeGraph:
    def __init__(
        self,
        repo_path: str,
        *,
        cache: bool = True,
        languages: list[str] | None = None,  # None = all supported
    ) -> None:
        """Initialize CodeGraph for a repository.

        Parses the codebase (or loads from cache) and builds the dependency graph.
        Subsequent calls use cache — only changed files are re-parsed.

        Args:
            repo_path: Absolute or relative path to the repository root.
            cache: Whether to use persistent SQLite cache (default True).
            languages: Restrict to specific languages (default: all supported).
        """

    def context_for(
        self,
        files: list[str],
        token_budget: int = 4096,
        *,
        format: str = "markdown",
    ) -> str:
        """Get ranked context relevant to specific files.

        Biases the ranking toward the given files and their dependency neighborhood.
        Returns context that fits within the token budget, most important symbols first.

        Args:
            files: Relative file paths the agent will edit.
            token_budget: Maximum tokens for the output (default 4096).
            format: Output format — "markdown" (default) or "json".
        """

    def query(
        self,
        text: str,
        token_budget: int = 4096,
        *,
        format: str = "markdown",
    ) -> str:
        """Get ranked context relevant to a natural language query.

        Finds files matching query keywords (file names, symbol names),
        then ranks by graph importance biased toward matches.

        Args:
            text: Keywords or natural language query.
            token_budget: Maximum tokens for the output (default 4096).
            format: Output format — "markdown" (default) or "json".
        """

    def repo_map(
        self,
        token_budget: int = 2048,
        *,
        format: str = "markdown",
    ) -> str:
        """Get a global repo map ranked by structural importance.

        No task bias — shows the most structurally important files and symbols
        across the entire repository.

        Args:
            token_budget: Maximum tokens for the output (default 2048).
            format: Output format — "markdown" (default) or "json".
        """

    def refresh(self) -> None:
        """Re-scan the repository for changes and update the index.

        Only re-parses files whose content hash has changed.
        Call this if the repo has changed since the CodeGraph was created.
        """

    @property
    def graph(self) -> nx.DiGraph:
        """The underlying NetworkX dependency graph. Read-only."""

    @property
    def symbols(self) -> dict[str, list[Symbol]]:
        """All symbols indexed by file path. Read-only."""

    @property
    def stats(self) -> dict:
        """Index statistics: file count, symbol count, edge count, languages, etc."""
```

### 8. `cli.py` — Command-Line Interface

**Responsibility**: Expose CodeGraph functionality via CLI for quick use.

```
codegraph map /path/to/repo                    # Global repo map (2048 tokens)
codegraph map /path/to/repo --budget 4096      # Custom budget
codegraph context /path/to/repo src/auth.py    # Context for specific files
codegraph context /path/to/repo src/auth.py src/middleware.py --budget 8192
codegraph query /path/to/repo "authentication" # Query-based context
codegraph stats /path/to/repo                  # Index statistics
codegraph clear /path/to/repo                  # Clear cache
codegraph --version                            # Version
codegraph --help                               # Help
```

Use `click` for CLI framework (consistent with Forge).

---

## Dependencies

```toml
[project]
name = "codegraph"
version = "0.1.0"
description = "Ranked, token-budget-aware code context for LLMs and AI agents"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [{name = "Tarun M S"}]
readme = "README.md"
keywords = ["llm", "ai", "code", "context", "tree-sitter", "agents", "codegraph"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Topic :: Software Development :: Libraries",
]

dependencies = [
    "tree-sitter>=0.23",
    "tree-sitter-language-pack>=0.2",
    "networkx>=3.0",
    "tiktoken>=0.5",
    "click>=8.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "ruff>=0.3",
]

[project.scripts]
codegraph = "codegraph.cli:main"

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## Tree-Sitter Query Files (.scm)

Each language needs a query file in `codegraph/queries/` that extracts definitions and references.

### Example: `python.scm`

```scheme
; --- Definitions ---

; Top-level function
(function_definition
  name: (identifier) @name.definition.function)

; Method inside a class
(class_definition
  body: (block
    (function_definition
      name: (identifier) @name.definition.method)))

; Class
(class_definition
  name: (identifier) @name.definition.class)

; Top-level assignment (constants/variables)
(module
  (expression_statement
    (assignment
      left: (identifier) @name.definition.variable)))

; --- References ---

; import foo
(import_statement
  name: (dotted_name) @name.reference.import)

; from foo import bar
(import_from_statement
  module_name: (dotted_name) @name.reference.import)

; Class inheritance: class X(Base)
(class_definition
  superclasses: (argument_list
    (identifier) @name.reference.inherit))
```

### Example: `typescript.scm`

```scheme
; --- Definitions ---

; Function declaration
(function_declaration
  name: (identifier) @name.definition.function)

; Arrow function assigned to variable
(lexical_declaration
  (variable_declarator
    name: (identifier) @name.definition.function
    value: (arrow_function)))

; Class declaration
(class_declaration
  name: (type_identifier) @name.definition.class)

; Interface declaration
(interface_declaration
  name: (type_identifier) @name.definition.interface)

; Type alias
(type_alias_declaration
  name: (type_identifier) @name.definition.type)

; Method definition
(method_definition
  name: (property_identifier) @name.definition.method)

; Enum
(enum_declaration
  name: (identifier) @name.definition.enum)

; --- References ---

; import { X } from './module'
(import_statement
  source: (string) @name.reference.import)

; Class extends
(class_heritage
  (extends_clause
    value: (identifier) @name.reference.inherit))

; Class implements
(class_heritage
  (implements_clause
    (type_identifier) @name.reference.implement))
```

Write similar query files for all 13 supported languages. Each query must extract:
1. All definition types (class, function, method, variable, type, interface, enum)
2. Import/require references
3. Inheritance/implementation references

Refer to tree-sitter's official grammar repositories for the correct node types per language. Test each query file against the fixtures.

---

## Testing Requirements

### Unit Tests

**test_parser.py** — Symbol extraction accuracy:
- Parse a Python file → verify correct symbols extracted (names, kinds, lines, signatures)
- Parse a TypeScript file → same verification
- Parse a file with syntax errors → verify partial results, no crash
- Parse an empty file → verify empty FileInfo, no crash
- Parse a binary file → verify it's skipped
- Parse a file with no symbols (plain text) → verify empty symbols list
- Parse a large file (1000+ lines) → verify all symbols found
- Verify signature extraction accuracy: function params, return types, decorators stripped

**test_graph.py** — Graph construction:
- Build graph from Python project fixture → verify correct edges (imports, inheritance, tests)
- Build graph from TypeScript project fixture → verify correct edges
- Build graph from mixed project (Python + TS) → verify cross-language files are separate nodes
- Verify circular imports don't cause infinite loops
- Verify test file detection: `test_auth.py` creates TESTS edge to `auth.py`
- Verify unresolvable references (external packages) are skipped, not errored
- Verify edge deduplication

**test_ranker.py** — Ranking correctness:
- Global ranking: most-imported file ranks highest
- Personalized ranking: task files and their neighbors rank highest
- Query ranking: files matching query keywords rank highest
- Disconnected files: still get a rank (not zero)
- Single-file repo: returns rank 1.0
- Empty graph: returns empty dict

**test_renderer.py** — Token budget compliance:
- Render with budget 4096 → output ≤ 4096 tokens
- Render with budget 100 → output ≤ 100 tokens (may be very truncated)
- Render with budget 0 → empty string
- Render with budget 1000000 → all files included
- Verify Tier 1 files have full signatures
- Verify Tier 2 files have names only
- Verify Tier 3 files have one-line summaries
- Verify markdown format is valid
- Verify JSON format is valid and parseable

**test_cache.py** — Cache correctness:
- Put and get → returns same FileInfo
- Get with wrong hash → returns None
- Get for missing file → returns None
- Invalidate → subsequent get returns None
- Clear → all entries gone
- Concurrent access: two threads reading/writing → no corruption
- Cache survives process restart (persistent SQLite)

**test_languages.py** — Language detection:
- Verify all 13 supported languages are detected from extensions
- Verify unsupported extensions return None
- Verify parser creation doesn't crash for any supported language
- Verify query loading works for all supported languages

### Integration Tests

**test_codegraph.py** — End-to-end:
- CodeGraph on python_project fixture → context_for() returns relevant symbols
- CodeGraph on typescript_project fixture → context_for() returns relevant symbols
- CodeGraph on mixed_project fixture → handles multi-language correctly
- CodeGraph with cache=True → second instantiation is faster (cache hit)
- CodeGraph.refresh() after file change → returns updated context
- CodeGraph on edge_cases fixture → no crashes, graceful handling
- CodeGraph on single_file fixture → works correctly
- Token budget is always respected across all methods

**test_cli.py** — CLI:
- `codegraph map fixtures/python_project` → prints repo map
- `codegraph context fixtures/python_project app.py` → prints context
- `codegraph stats fixtures/python_project` → prints statistics
- `codegraph --version` → prints version
- Invalid path → helpful error message

---

## GitHub Repository Setup

```
codegraph/
├── .github/
│   └── workflows/
│       └── ci.yml              # Run tests + lint on PR
├── codegraph/                   # Source package
│   └── (all modules above)
├── tests/                       # Test suite
│   └── (all tests above)
├── pyproject.toml               # Package config (contents specified above)
├── LICENSE                      # MIT License
├── README.md                    # See below
└── .gitignore
```

### CI Workflow (`.github/workflows/ci.yml`)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e '.[dev]'
      - run: ruff check codegraph/ tests/
      - run: ruff format --check codegraph/ tests/
      - run: pytest --cov=codegraph --cov-report=term-missing -q
```

### README.md

Write a clear README with:
1. One-line description: "Ranked, token-budget-aware code context for LLMs and AI agents."
2. Why: "Wrong context is worse than no context. codegraph gives your agents exactly what they need."
3. Install: `pip install codegraph`
4. Quick start: 5 lines of code showing `context_for()`
5. API reference: all three methods + properties
6. CLI usage
7. Supported languages list
8. How it works (brief): tree-sitter → dependency graph → PageRank → token-budget rendering
9. Performance: "<3 seconds first index, milliseconds on update"
10. License: MIT

Keep it under 200 lines. No fluff.

---

## What This Plan Does NOT Include (Explicitly Out of Scope)

- **Embedding/vector search**: Not needed. Graph-based ranking is more accurate and free.
- **LLM-generated summaries**: Can be added later as an optional layer. Core library is LLM-free.
- **MCP server**: Can be built as a separate thin wrapper. Core library is a Python library, not a server.
- **IDE plugins**: Out of scope. Library can be used by plugin authors.
- **Cross-session memory**: Different problem. Out of scope.
- **Code modification/editing**: Read-only. We analyze code, we don't change it.

---

## Critical Corrections (From Double Review)

These corrections OVERRIDE any conflicting specification above. The implementation MUST follow these corrections.

### C1. Python 3.11+ minimum (not 3.10)
`StrEnum` requires Python 3.11. Change `requires-python = ">=3.11"` in pyproject.toml. Change `target-version = "py311"` in ruff config.

### C2. Use `nx.MultiDiGraph` (not `nx.DiGraph`)
Standard DiGraph allows only one edge per node pair. We need multiple edge kinds between the same files (file A both imports and inherits from file B). Use `nx.MultiDiGraph` everywhere. Update all type hints accordingly.

### C3. Reduce launch languages to 6
Ship these 6 languages with TESTED, CORRECT .scm query files:
- Python, TypeScript, JavaScript, Go, Rust, Java

The remaining 7 (C, C++, Ruby, C#, Swift, Kotlin, PHP) are follow-up. Do NOT ship broken query files. Better to return "unsupported language" than to return wrong symbols.

Update `SUPPORTED_LANGUAGES` and `queries/` directory accordingly. Remove the other .scm files from the plan.

### C4. Add `[build-system]` to pyproject.toml
```toml
[build-system]
requires = ["setuptools>=68.0", "setuptools-scm>=8.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["codegraph*"]

[tool.setuptools.package-data]
codegraph = ["queries/*.scm", "py.typed"]
```

### C5. Use `Literal` for format parameter
```python
from typing import Literal

Format = Literal["markdown", "json"]
```
Use `format: Format = "markdown"` in all method signatures.

### C6. Import resolution — explicit rules

**Python import resolution order**:
1. `import foo` or `from foo import bar`:
   a. Look for `foo.py` in same directory
   b. Look for `foo/__init__.py`
   c. Look for `foo.py` in repo root
   d. Look for `foo/` as a package anywhere in repo
   e. If none match: skip (external package)
2. `from foo.bar import baz`:
   a. Look for `foo/bar.py`
   b. Look for `foo/bar/__init__.py`
   c. If none match: skip
3. Relative imports (`from .models import X`): resolve relative to current file's directory
4. `__init__.py` re-exports: when `foo/__init__.py` contains `from .bar import X`, and we see `from foo import X`, resolve to `foo/bar.py`

**TypeScript/JavaScript import resolution order**:
1. `import from './auth'`:
   a. Look for `./auth.ts`
   b. Look for `./auth.tsx`
   c. Look for `./auth.js`
   d. Look for `./auth.jsx`
   e. Look for `./auth/index.ts`
   f. Look for `./auth/index.js`
   g. If none match: skip
2. Non-relative imports (`import from 'lodash'`): skip (external package)

**Go import resolution**:
1. Match import path suffix against repo directory structure
2. External packages (not in repo): skip

**Rust import resolution**:
1. `use crate::module::Item` → resolve `module` to `src/module.rs` or `src/module/mod.rs`
2. `use super::` → resolve relative to parent module
3. External crates: skip

**Java import resolution**:
1. `import com.example.Foo` → look for `com/example/Foo.java` or matching class name
2. Wildcard imports (`import com.example.*`): resolve to directory
3. External packages: skip

### C7. Symbol name collision resolution
When multiple files define the same symbol name:
1. Prefer the file in the same directory as the importing file
2. Prefer the file in the same top-level package
3. If still ambiguous: create edges to ALL matching files (let PageRank sort by importance)

### C8. Signature extraction method
To extract a signature from a tree-sitter node:
1. Get the node's start byte and end byte from the source content
2. Read the source text for that byte range
3. Take only the first line (up to the first `\n`)
4. Strip trailing `:`, `{`, or whitespace
5. Truncate to 200 chars with `...` if longer
6. This gives us `def authenticate(token: str) -> User` not the full function body

### C9. Docstring extraction for Tier 3 summaries
Add to the parser: after extracting a class or module definition, check if the next sibling node (or first child block's first expression) is a `string` or `expression_statement` containing a string. If so, extract the first line of that string as the docstring.

For languages without docstrings (Go, Rust, Java), use the comment immediately above the first symbol as the file summary.

If no docstring or comment is found, generate a summary from the file's symbol names: `"Defines: ClassName, function_name, other_function"`.

### C10. Non-git repo fallback
When `git ls-files` fails (not a git repo):
1. Walk the directory tree recursively
2. Skip hidden directories (starting with `.`)
3. Skip common ignore patterns: `node_modules/`, `__pycache__/`, `.git/`, `venv/`, `.venv/`, `dist/`, `build/`, `*.egg-info/`, `target/` (Rust)
4. Skip files larger than 1MB (likely generated/binary)
5. Limit to 10,000 files maximum
6. Log a warning: "Not a git repository, using directory walk. Results may include untracked files."

### C11. Cache write permission fallback
When creating `.codegraph/` fails (read-only repo):
1. Try `{repo_root}/.codegraph/`
2. If permission denied: fall back to `~/.cache/codegraph/{sha256(repo_path)[:16]}/`
3. Log the actual cache location at DEBUG level
4. If `cache=False` was passed to CodeGraph: skip all disk I/O, cache in memory only

### C12. Thread safety for SQLite cache
Use `sqlite3.connect(db_path, check_same_thread=False)` and protect all read/write operations with a `threading.Lock()`. This is simpler and safer than connection pooling for a library.

### C13. Logging strategy
```python
import logging
logger = logging.getLogger("codegraph")
```
- Use `logger.debug()` for: cache hits/misses, file parsing timing, graph construction details
- Use `logger.info()` for: index creation, file count, language detection summary
- Use `logger.warning()` for: unparseable files, unresolvable imports, cache fallback
- Use `logger.error()` for: nothing — raise exceptions instead
- NEVER use `print()` except in `cli.py`

### C14. `stats` property return shape
```python
@property
def stats(self) -> dict:
    """Returns:
    {
        "files": int,           # total indexed files
        "symbols": int,         # total symbols across all files
        "edges": int,           # total edges in dependency graph
        "languages": dict[str, int],  # language name → file count
        "cache_hits": int,      # files loaded from cache (last index)
        "cache_misses": int,    # files parsed fresh (last index)
        "index_time_ms": float, # time to build/refresh index in milliseconds
    }
    """
```

### C15. `__all__` exports in `__init__.py`
```python
__all__ = [
    "CodeGraph",
    "Symbol",
    "FileInfo",
    "Reference",
    "SymbolKind",
    "EdgeKind",
]
```

### C16. Custom exceptions
```python
# In codegraph/exceptions.py
class CodeGraphError(Exception):
    """Base exception for all codegraph errors."""

class ParseError(CodeGraphError):
    """Raised when a file cannot be parsed."""

class CacheError(CodeGraphError):
    """Raised when cache operations fail."""
```
Add `exceptions.py` to the architecture. Import exceptions in `__init__.py`.

### C17. `context_for()` with nonexistent files
If any file in the `files` list is not in the index:
- Log a warning for each missing file
- Proceed with the files that DO exist
- If ALL files are missing: return empty context with a comment `"<!-- No matching files found in index -->"` for markdown or `{"files": [], "error": "No matching files found"}` for JSON

### C18. `refresh()` must rebuild graph
After re-parsing changed files:
1. Update the `files` dict with new FileInfo
2. Remove old edges involving changed files
3. Re-resolve references for changed files
4. Re-add edges
5. Re-run PageRank on the full graph (it's fast — milliseconds even for large graphs)

### C19. Test file detection — smarter matching
To find what file a test file tests:
1. Get the test file's basename (e.g., `test_auth.py`)
2. Strip test prefixes/suffixes: `test_`, `_test`, `.test`, `.spec`, `Test` suffix
3. Result: `auth` (the "stem")
4. Search the repo for files named `auth.py`, `auth.ts`, `auth.go`, etc.
5. If multiple matches: prefer the one closest in directory structure (fewest `../` hops)
6. If in a `tests/` or `__tests__/` directory: also check the parallel source directory (`src/`, `lib/`, `app/`)
7. If no match found: don't create a TESTS edge (silently skip)

### C20. `.gitignore` for the codegraph repo itself
```
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.codegraph/
.eggs/
*.so
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/
```

### C21. Fixture file contents
Test fixtures MUST contain specific, known code that tests assert against. Each fixture file should have:
- At least 2-3 classes/functions with clear signatures
- Import statements referencing other fixture files
- At least one inheritance relationship
- Comments/docstrings for summary extraction testing

The Forge task that builds fixtures must write deterministic code — NOT placeholder comments like "# add code here". Every symbol, every import, every class hierarchy must be concrete and testable.

### C22. `queries/` directory loading at runtime
Use `importlib.resources` (Python 3.11+) to locate query files:
```python
from importlib.resources import files

def _load_query(language: str) -> str:
    query_file = files("codegraph.queries").joinpath(f"{language}.scm")
    return query_file.read_text(encoding="utf-8")
```
This works correctly whether the package is installed via pip, run from source, or inside a zip/wheel.

### C23. JSON output schema — strict contract
The JSON output from any method with `format="json"` MUST follow this exact schema:
```json
{
  "files": [
    {
      "path": "string",
      "rank": 0.0,
      "tier": 1,
      "language": "string",
      "summary": "string | null",
      "symbols": [
        {
          "name": "string",
          "kind": "string",
          "signature": "string",
          "line": 0,
          "parent": "string | null"
        }
      ]
    }
  ],
  "token_count": 0,
  "token_budget": 0,
  "files_included": 0,
  "files_total": 0
}
```
Symbols array may be empty for Tier 3 files. The `tier` field is always 1, 2, or 3.
