# Using codegraph with Planning Agents

A practical guide for planning agents (Forge, Aider, Claude Code, Cursor, etc.) to get optimal code context before planning tasks.

## 1. Why Context Matters for Planning

Wrong context is worse than no context. Research shows LLMs degrade when stuffed with irrelevant code — they hallucinate more, follow instructions worse, and produce lower-quality output. Planning agents need *structurally relevant* context: the files and symbols that actually matter for a task, ranked by importance. codegraph uses tree-sitter static analysis and PageRank to deliver exactly that, fitted to a token budget so agents never waste context window on noise.

## 2. Quick Start for Planning Agents

Three steps: initialize, get context, feed to LLM.

### File-targeted planning (you know which files to modify)

```python
from codegraph import CodeGraph

cg = CodeGraph("/path/to/repo")

# Get ranked context seeded on the files you plan to edit
context = cg.context_for(
    files=["src/auth.py", "src/models.py"],
    token_budget=4096,
)

# Feed to your LLM planning prompt
plan_prompt = f"""Given this codebase context:

{context}

Plan the implementation for: add rate limiting to the auth middleware.
"""
```

### Intent-based planning (natural language description)

```python
# Match keywords against symbol and file names — no embeddings, no APIs
context = cg.query("authentication middleware", token_budget=4096)
```

### Architectural overview (initial planning, onboarding)

```python
# Global repo map ranked by PageRank structural importance
overview = cg.repo_map(token_budget=2048)
```

## 3. Choosing the Right Method

| Scenario | Method | When to Use |
|---|---|---|
| Agent knows which files to modify | `context_for(files)` | Task decomposition, targeted edits, code review |
| Agent has natural language description | `query(text)` | Feature requests, bug reports, exploratory tasks |
| Agent needs architectural overview | `repo_map()` | Initial planning, onboarding, understanding structure |

**Rule of thumb:** prefer `context_for` when you know the files — it's more precise because it uses personalized PageRank seeded on those exact files. Use `query` when you only have a description. Use `repo_map` when you need the big picture before drilling in.

## 4. Token Budget Strategy

Planning context should typically be **2000-4000 tokens**. This leaves room for the plan itself, the task description, and the LLM's response within the context window.

### How the tier system works

codegraph partitions ranked files into tiers to maximize information density:

| Tier | Files | Detail Level | What's Included |
|------|-------|-------------|-----------------|
| Tier 1 | Top 30% | Full signatures | Class/function signatures with parameters |
| Tier 2 | Next 30% | Names only | Symbol names listed as bullet points |
| Tier 3 | Next 20% | Summary | File path + one-line summary of definitions |
| Tier 4 | Bottom 20% | Omitted | Not included (below relevance threshold) |

Output is trimmed to fit your exact token budget. Higher budgets promote more files into higher tiers; lower budgets focus on the most important files.

### JSON format for programmatic access

When agents need to process context programmatically (e.g., to select files for editing or to build structured prompts), use `format='json'`:

```python
import json

result = cg.context_for(["src/auth.py"], token_budget=4096, format="json")
data = json.loads(result)

# Structure:
# {
#   "files": [
#     {"path": "src/auth.py", "rank": 0.042, "tier": 1, "language": "python",
#      "summary": "Defines: AuthMiddleware, authenticate, verify_token",
#      "symbols": [{"name": "AuthMiddleware", "kind": "class", "signature": "...", ...}]},
#     ...
#   ],
#   "token_count": 847,
#   "token_budget": 4096,
#   "files_included": 8,
#   "files_total": 42
# }

# Select tier-1 files for detailed planning
critical_files = [f["path"] for f in data["files"] if f["tier"] == 1]
```

## 5. Integration Patterns

### Pattern A: Two-Pass Planning

Start broad, then focus. Useful when the agent doesn't know which files matter yet.

```python
from codegraph import CodeGraph

cg = CodeGraph("/path/to/repo")

# Pass 1: Get architectural overview to identify relevant areas
overview = cg.repo_map(token_budget=1500)
# LLM reads overview, identifies target files: ['src/auth.py', 'src/models.py']

# Pass 2: Get detailed context for those specific files
context = cg.context_for(
    files=["src/auth.py", "src/models.py"],
    token_budget=3000,
)
# LLM creates detailed implementation plan with full signature context
```

### Pattern B: Query-Driven Discovery

When the agent has a task description but no file list.

```python
# Single pass — codegraph finds the relevant files via keyword matching
context = cg.query("authentication middleware", token_budget=4096)
# LLM receives ranked context and plans from there
```

### Pattern C: JSON for Structured Consumption

When agents need to build structured prompts or select files programmatically.

```python
import json

cg = CodeGraph("/path/to/repo")
result = cg.context_for(["src/auth.py"], token_budget=4096, format="json")
data = json.loads(result)

# Build a focused planning prompt from tier-1 files only
tier1_context = []
for f in data["files"]:
    if f["tier"] == 1:
        signatures = "\n".join(s["signature"] for s in f["symbols"] if s.get("signature"))
        tier1_context.append(f"### {f['path']}\n{signatures}")

planning_context = "\n\n".join(tier1_context)
```

### Pattern D: Multi-Task Planning

When planning multiple related tasks, reuse the same `CodeGraph` instance.

```python
cg = CodeGraph("/path/to/repo")

# Plan task 1: auth changes
auth_context = cg.context_for(["src/auth.py"], token_budget=3000)

# Plan task 2: database changes (same graph, no re-indexing)
db_context = cg.context_for(["src/db.py", "src/migrations.py"], token_budget=3000)
```

## 6. Refresh Strategy

After modifying files, the dependency graph may be stale. Call `refresh()` to re-index.

```python
cg = CodeGraph("/path/to/repo")

# Initial planning
context = cg.context_for(["src/auth.py"], token_budget=4096)

# ... agent writes code ...

# Re-index to pick up changes (only re-parses modified files via SHA-256 hash)
cg.refresh()

# Get updated context for next planning step
context = cg.context_for(["src/auth.py"], token_budget=4096)
```

- **After file modifications:** always call `cg.refresh()` before getting new context.
- **Long-running agents:** refresh periodically between planning cycles.
- **Performance:** the SQLite cache makes re-indexing fast — only changed files are re-parsed.

## 7. CLI Usage for Non-Python Agents

Agents that don't run Python (shell-based tools, VS Code extensions calling subprocesses) can use the CLI directly.

### Equivalent commands

```bash
# Architectural overview (repo_map)
codegraph map ./repo --budget 2048

# File-targeted context (context_for)
codegraph context ./repo src/auth.py src/models.py --budget 4096

# Natural language query (query)
codegraph query ./repo "authentication middleware" --budget 4096

# Index statistics
codegraph stats ./repo

# Clear cache (force full re-index)
codegraph clear ./repo
```

### Machine-readable output

All commands accept `--format json` for structured output:

```bash
# JSON output for programmatic consumption
codegraph context ./repo src/auth.py --budget 4096 --format json

# Pipe to jq for extraction
codegraph context ./repo src/auth.py --budget 4096 --format json | jq '.files[] | select(.tier == 1) | .path'
```

The JSON schema is the same as the Python API — see the structure in [Section 4](#4-token-budget-strategy).

### Shell integration example

```bash
#!/bin/bash
# Two-pass planning from shell

# Pass 1: broad overview
OVERVIEW=$(codegraph map ./repo --budget 1500 --format json)

# Extract top-ranked files
TOP_FILES=$(echo "$OVERVIEW" | jq -r '.files[] | select(.tier == 1) | .path')

# Pass 2: detailed context for those files
CONTEXT=$(codegraph context ./repo $TOP_FILES --budget 3000)

# Feed to LLM via your preferred interface
echo "$CONTEXT" | your-llm-tool plan --stdin
```

## 8. Best Practices

- **Don't stuff the entire repo into context.** codegraph exists to prevent this. Let PageRank select what matters.
- **Use `format='json'`** when the agent needs to programmatically process results (file selection, structured prompts).
- **Use `format='markdown'`** when feeding directly to an LLM prompt (human-readable, well-structured).
- **Prefer `context_for` over `query`** when you know the files — personalized PageRank is more precise than keyword matching.
- **Re-index after writing files.** Call `cg.refresh()` to keep the graph accurate. The cache makes this fast.
- **Budget conservatively.** 2000-4000 tokens for context leaves room for the task, the plan, and the LLM's response.
- **Reuse `CodeGraph` instances.** Initialization indexes the repo; subsequent calls are cheap.
- **Tier-1 files are your priority.** If you need to cut context further, filter to `tier == 1` in JSON output.
- **Cache directory:** codegraph stores its SQLite cache in `.codegraph/` at the repo root. Add it to `.gitignore`.
