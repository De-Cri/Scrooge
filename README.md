![Scrooge presentation image](ScroogeMcDuck.jpg)

# Scrooge

**Pre-edit situational awareness for AI coding agents.**

Before an agent touches a file, Scrooge tells it the full scope of the change: what the file structurally calls, and — crucially — which other files have historically been edited *together with it* in the same commits, even without a direct code relationship.

This prevents the most common agent failure mode: **incomplete edits** — fixing the right file but missing the coupled module that also needed to change.

Available as a **CLI tool** and **MCP server** (plug directly into Claude Code and other agents).

---

## The Problem

~35% of AI agent coding failures are **incomplete edits** (SWE-bench, 2024): the agent fixed the right location but missed a coupled module. Call-graph tools like Aider's repo map can't catch this — they only see structural connections (A calls B), not behavioral ones (A and B are always edited together).

## How Scrooge Addresses It

Scrooge combines two signals:

**1. Structural call graph** — which functions call which, ranked by graph distance + PageRank. Finds the files directly involved in a query.

**2. Co-change graph** — mined from `git log`. Finds files that have historically been modified *in the same commits*, even with no direct code relationship. These are the implicit dependencies: shared invariants, parallel implementations, configuration that moves with logic.

Given a query or a file the agent is about to edit, Scrooge returns:
- Candidate files to read (structural)
- Co-change alerts: files that will *almost certainly* also need editing (behavioral)

---

## Benchmark Results

### Co-change: incomplete edit prevention

Tested on real git history from two Python libraries (50+ test cases total). **Ground truth:** commits that changed multiple source files simultaneously. **Task:** given one file, does the tool surface the others that were also edited?

| Tool | Recall@1 | Recall@3 | Recall@5 | MRR |
|------|----------|----------|----------|-----|
| Structural only (Aider-style) | 0.135 | 0.172 | 0.183 | 0.271 |
| Co-change only | 0.220 | 0.394 | 0.548 | 0.447 |
| **Scrooge combined** | **0.278** | **0.449** | **0.557** | **0.528** |

**Scrooge combined vs. Aider-style structural: +204% Recall@5, +95% MRR.**

In 56% of real multi-file edits, Scrooge correctly surfaces all required co-changed files in the top 5. Structural-only navigation achieves 18%.

### File navigation: finding the right module

Tested on 16 ground-truth queries across three Python repos (small/medium/large).

| Metric | Result |
|--------|--------|
| Recall (correct file returned at all) | **100%** |
| Hit@1 (correct file ranked #1) | **75%** |
| Hit@3 (correct file in top 3) | **94%** |
| File reduction vs. keyword grep | **10.5×** |

Full methodology: [`benchmarks/BENCHMARK_REPORT.md`](benchmarks/BENCHMARK_REPORT.md) and [`benchmarks/COCHANGE_REPORT.md`](benchmarks/COCHANGE_REPORT.md)

---

## How It Works

```
repo
 └── Scanner        → find all .py files
      └── Parser    → extract functions, classes, calls (Python AST)
           └── Graph Builder  → directed call graph (NetworkX)
                └── Ranker    → score nodes by query relevance
                     │          (graph distance + normalized PageRank + token coverage)
                     └── CLI / MCP  → return 2–3 ranked files with call context
```

### Query flow

Scrooge matches queries by **substring against code identifiers** — function names, class names, method names, file names. For best results, pass symbol-oriented keywords, not natural language:

```
User: "how does the authentication flow work?"
         ↓
   Agent extracts keywords (built into MCP description)
         ↓
Scrooge query: "auth login authenticate"
         ↓
   Matches: auth.py → authenticate(), login_user()
         ↓
Returns: auth.py (relevance 100) + utils.py (relevance 72)
         with calls/called_by for each
```

This keyword extraction step is baked into the MCP tool descriptions, so agents using Claude Code do it automatically.

### Output example

```json
{
  "candidates": [
    {
      "file": "/path/to/auth.py",
      "relevance": 100,
      "matches": [{"symbol": "login_user", "line": 42}, {"symbol": "authenticate", "line": 61}],
      "calls": ["utils.normalize_username", "db.get_user"],
      "called_by": ["api.login_endpoint"]
    }
  ]
}
```

The agent reads `auth.py` starting at line 42. It knows before opening the file that it calls `utils` and `db`, and that the API layer calls into it.

---

## Installation

**Prerequisites:** Python 3.11+, uv (recommended) or pip

```bash
git clone https://github.com/De-Cri/Scrooge.git
cd Scrooge
uv pip install -e .
```

Both `scrooge` (CLI) and `scrooge-mcp` (MCP server) are installed.

---

## Setup as MCP Server (Claude Code)

Open your Claude Code settings file:

| OS | Path |
|---|---|
| macOS / Linux | `~/.claude/settings.json` |
| Windows | `%USERPROFILE%\.claude\settings.json` |

Add the `Scrooge` block inside `mcpServers`:

**With uv (recommended):**
```json
{
  "mcpServers": {
    "Scrooge": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/Scrooge", "scrooge-mcp"]
    }
  }
}
```

**With venv (Windows):**
```json
{
  "mcpServers": {
    "Scrooge": {
      "command": "C:/path/to/Scrooge/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_server.scrooge_mcp"],
      "cwd": "C:/path/to/Scrooge"
    }
  }
}
```

Restart Claude Code. The `architecture`, `connections`, and `index` tools appear automatically. Claude will use them when exploring codebases — you don't need to prompt it differently.

---

## CLI Usage

### `architecture` — find files relevant to a query

```bash
scrooge architecture path/to/repo auth login
```

```json
{
  "candidates": [
    {
      "file": "auth.py",
      "relevance": 100,
      "matches": [{"symbol": "login_user", "line": 42}],
      "calls": ["utils.normalize_username"],
      "called_by": ["api.login_endpoint"]
    }
  ]
}
```

Options:
- `--rank-keep-pct` (default 0.3) — fraction of top-ranked graph nodes to keep
- `--file-keep-pct` (default 0.35) — fraction of top-ranked files to keep

### `connections` — trace call paths around matched symbols

```bash
scrooge connections path/to/repo auth login 2
scrooge connections path/to/repo auth login 2 --compact
```

---

## MCP Tools

| Tool | What it does |
|------|-------------|
| `architecture` | Returns ranked candidate files with matches, calls, called_by. Saves result to `.scrooge_architecture.json` in the repo root — agents can re-read it without calling the tool again. |
| `connections` | Returns the raw call graph around matched symbols (BFS, configurable depth). |
| `index` | Returns the full parsed structure + graph for the repo. |

---

## Project Structure

```
Scrooge/
├── scanner/scanner.py               # find source files
├── parser/ast_parser.py             # Python AST → functions, classes, calls
├── indexer/symbol_extractor.py      # match query tokens to symbol names + token coverage scoring
├── graph_builder/
│   ├── call_graph.py                # build NetworkX directed call graph
│   └── symbols_connections.py       # BFS traversal + connection output
├── intelligence/rank_graph_connections.py  # node ranking (normalized PageRank + distance)
├── cli/scrooge_cli.py               # CLI entry point
├── mcp_server/scrooge_mcp.py        # MCP server entry point
└── benchmarks/
    ├── objective_benchmark.py        # reproducible benchmark harness
    └── BENCHMARK_REPORT.md          # full results and analysis
```

---

## Current Limitations

- **Python only** — AST parsing is implemented for Python. JS/TS file discovery exists but parsing is not implemented yet.
- **No caching** — every query re-parses the repo. Fast enough today (0.3–0.8s), but would need a cache for very large repos or high query frequency.
- **Keyword queries only** — Scrooge matches identifiers, not semantics. For vague conceptual questions, a semantic embedding search is complementary.
- **Call resolution is best-effort** — dynamic dispatch, decorators, and `functools.partial` are invisible to static AST analysis.

---

## License

MIT
