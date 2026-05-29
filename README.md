![Scrooge presentation image](ScroogeMcDuck.jpg)

# Scrooge

**A call-graph navigator for AI coding agents. Finds the 2–3 files that matter instead of the 25 that contain the keyword.**

Scrooge scans a Python repository, builds a **function-level call graph**, and answers queries like *"what touches authentication?"* by returning a ranked, connection-annotated list of candidate files — not raw search results.

Available as a **CLI tool** and **MCP server** (plug directly into Claude Code and other agents).

---

## Why

When an AI agent needs to understand a codebase, it either reads everything (expensive) or greps for keywords (imprecise). Neither approach scales.

Scrooge does something different: it pre-builds the repo's call graph and uses it to answer queries structurally. Given a query, it:

1. Matches symbols by name (functions, classes, methods)
2. Ranks them using graph distance + PageRank
3. Returns only the files whose symbols are central to the query — along with what those files call and who calls them

The agent reads 2 files instead of 20. It also knows immediately which module is the entry point and which is the dependency — without opening anything.

---

## Benchmark Results

Tested on 16 ground-truth queries across three Python repos (small: 24 files, medium: 37 files, large: 5,000+ files). For each case the correct target file is known in advance.

| Metric | Result |
|--------|--------|
| **Recall (correct file returned at all)** | **100%** |
| **Hit@1 (correct file ranked #1)** | **75%** |
| **Hit@3 (correct file in top 3)** | **94%** |
| **Avg files returned** | **2.2** |
| **Avg files a keyword grep returns** | **25.6** |
| **File reduction vs. grep** | **10.5×** |
| **Avg query time** | **0.3s** |

The full methodology, per-case breakdown, and comparison with semantic search and LSP is in [`benchmarks/BENCHMARK_REPORT.md`](benchmarks/BENCHMARK_REPORT.md).

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
