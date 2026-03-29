# codegraph

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/codegraph.svg)](https://pypi.org/project/codegraph/)

**Ranked, token-budget-aware code context for LLMs and AI agents.**

Wrong context is worse than no context. Research shows LLMs degrade when stuffed with irrelevant code — they hallucinate more, follow instructions worse, and produce lower-quality output. codegraph uses tree-sitter static analysis and PageRank to give your agents exactly the files and symbols they need, nothing more.

## What It Does

```
Input:  "Which files matter for authentication?"
Output: Ranked symbols + signatures, fitted to your token budget
```

```python
from codegraph import CodeGraph

cg = CodeGraph("/path/to/repo")
context = cg.context_for(["src/auth.py"], token_budget=4096)
print(context)
```

```markdown
## Relevant Context

### src/auth.py
> Defines: AuthMiddleware, authenticate, verify_token, create_session, revoke_token

​```python
class AuthMiddleware:
def authenticate(request: Request) -> User:
def verify_token(token: str) -> Claims:
​```

### src/models.py
> Defines: User, Session, Token

- User
- Session
- Token

### Related files
- `src/middleware.py` — Defines: RequestHandler, ResponseHandler
- `src/config.py` — Defines: Settings, get_config
```

Top-ranked files get full signatures. Lower-ranked files get names only. The bottom tier gets a one-line summary. Everything fits within your token budget.

## Install

```
pip install codegraph
```

No external services. No embedding APIs. No GPU. Pure local computation.

## Quick Start

```python
from codegraph import CodeGraph

cg = CodeGraph("/path/to/repo")

# Context for specific files (agent orchestrators, IDE tools)
context = cg.context_for(
    files=["src/auth.py", "src/middleware.py"],
    token_budget=4096,
)

# Context for a natural language query (chat tools, search)
context = cg.query("authentication middleware", token_budget=4096)

# Full repo map (Aider-style tools)
repo_map = cg.repo_map(token_budget=2048)

# Refresh after file changes (only re-parses what changed)
cg.refresh()
```

## API Reference

### `CodeGraph(repo_path, *, cache=True, languages=None)`

Initialize and index a repository.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `repo_path` | `str` | — | Path to the repository root |
| `cache` | `bool` | `True` | Enable SQLite-backed file cache |
| `languages` | `list[str] \| None` | `None` | Filter to specific languages (e.g. `["python", "typescript"]`) |

### `cg.context_for(files, token_budget=4096, *, format="markdown")`

Get ranked context relevant to specific files. Uses personalized PageRank seeded on the given files to find the most structurally relevant code.

```python
context = cg.context_for(["src/auth.py"], token_budget=4096)
context_json = cg.context_for(["src/auth.py"], token_budget=4096, format="json")
```

### `cg.query(text, token_budget=4096, *, format="markdown")`

Get ranked context for a natural language query. Matches keywords against symbol and file names — no embeddings, no external APIs.

```python
context = cg.query("database connection pooling", token_budget=4096)
```

### `cg.repo_map(token_budget=2048, *, format="markdown")`

Generate a global repo map ranked by structural importance (PageRank). Useful for giving LLMs a high-level overview of the entire codebase.

```python
overview = cg.repo_map(token_budget=2048)
```

### `cg.refresh()`

Re-scan the repository and update the index. Only re-parses files whose content has changed (SHA-256 hash comparison).

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `cg.graph` | `nx.MultiDiGraph` | The underlying NetworkX dependency graph |
| `cg.symbols` | `dict[str, list[Symbol]]` | All symbols indexed by file path |
| `cg.stats` | `dict` | Index statistics (files, symbols, edges, timing) |

## CLI Usage

codegraph ships with a CLI for quick exploration:

```bash
# Global repo map
codegraph map ./my-project --budget 2048

# Context for specific files
codegraph context ./my-project src/auth.py src/models.py --budget 4096

# Natural language query
codegraph query ./my-project "authentication middleware"

# Index statistics
codegraph stats ./my-project

# Clear the cache
codegraph clear ./my-project

# Version
codegraph --version
```

All commands accept `--format json` for machine-readable output.

## How It Works

1. **Parse** — tree-sitter extracts every symbol (classes, functions, methods, types) and reference from each source file. Language-specific `.scm` queries ensure accurate extraction.

2. **Graph** — Symbols and their relationships (imports, calls, inheritance, type usage) form a directed dependency graph via NetworkX.

3. **Rank** — PageRank scores every file by structural importance. For targeted queries, personalized PageRank biases toward the files or keywords you care about.

4. **Render** — Files are partitioned into tiers by rank. Top 30% get full signatures, next 30% get names only, next 20% get a one-line summary, bottom 20% are omitted. Output is trimmed to fit your exact token budget.

## Supported Languages

| Language | Extensions | Status |
|----------|-----------|--------|
| Python | `.py`, `.pyi` | Stable |
| TypeScript | `.ts`, `.tsx` | Stable |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | Stable |
| Go | `.go` | Stable |
| Rust | `.rs` | Stable |
| Java | `.java` | Stable |

## Performance

First index of a 500-file repo completes in under 3 seconds. Subsequent calls take milliseconds — codegraph hashes every file and only re-parses what changed. Results are cached in a thread-safe SQLite database stored in `.codegraph/` at the repo root.

Zero external services. Zero network calls. Works offline, on CI, in Docker, anywhere Python runs.

## JSON Output

All methods accept `format="json"` for structured output:

```json
{
  "files": [
    {
      "path": "src/auth.py",
      "rank": 0.042,
      "tier": 1,
      "language": "python",
      "summary": "Defines: AuthMiddleware, authenticate, verify_token",
      "symbols": [
        {
          "name": "AuthMiddleware",
          "kind": "class",
          "signature": "class AuthMiddleware:",
          "line": 12,
          "parent": null
        }
      ]
    }
  ],
  "token_count": 847,
  "token_budget": 4096,
  "files_included": 8,
  "files_total": 42
}
```

## License

MIT — see [LICENSE](LICENSE) for details.
