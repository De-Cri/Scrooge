# Scrooge — Technical Documentation

This document covers how Scrooge works internally, its API surface, and how to extend it.

For installation and quick start, see [README.md](README.md).

---

## How It Works

Scrooge builds a **function-level dependency graph** of a repository and uses it to answer queries with minimal context. The pipeline has five stages:

```
1. Scanner    → discover source files
2. Parser     → extract functions, classes, and calls via AST
3. Graph      → build a directed call graph (NetworkX)
4. Ranker     → score nodes by query relevance (PageRank + distance)
5. Output     → return ranked files and connections as JSON
```

### 1. Scanner

**Module:** `scanner/scanner.py`

```python
scan_repo(root_path: str) -> list[Path]
```

Recursively finds all source files in a directory. Currently supports `.py`, `.js`, and `.ts` extensions.

**Ignored directories:** `.git`, `node_modules`, `__pycache__`, `dist`, `build`, `.venv`

> **Note:** Only Python files are fully parsed today. JS/TS files are discovered but not parsed yet — parsers for additional languages are planned.

### 2. Parser

**Module:** `parser/ast_parser.py`

```python
parse_file(file_path) -> dict
```

Uses Python's `ast` module to extract:
- **Functions** — name and list of calls made
- **Classes** — name and methods, each with their calls
- **Imports** — resolved to full qualified names (including relative imports)

Returns a structured dict:

```python
{
    "files": {
        "auth.py": {
            "functions": {
                "login_user": {
                    "calls": ["auth.audit_login", "utils.normalize_username"]
                }
            },
            "classes": {
                "AuthService": {
                    "methods": {
                        "authenticate": {
                            "calls": ["auth.get_user"]
                        }
                    }
                }
            }
        }
    }
}
```

**Call resolution:** When the parser encounters a function call, it resolves it through:
1. Import map — if the name was imported, resolve to the full module path
2. Class scope — if inside a class and `self.method()`, resolve to `module.Class.method`
3. Local scope — if the function is defined in the same file, resolve to `module.function`
4. Raw name — if unresolved, keep as-is

**Error handling:** Files that fail to parse (syntax errors, encoding issues) are silently skipped and returned as empty structures.

### 3. Graph Builder

**Module:** `graph_builder/call_graph.py`

```python
build_graph(parsed_data: dict) -> nx.DiGraph
```

Builds a NetworkX directed graph where:
- **Nodes** are qualified symbol names: `module.function` or `module.Class.method`
- **Edges** represent call relationships: `A → B` means "A calls B"

Only edges to **internal nodes** (symbols defined within the repo) are created. External library calls are ignored.

**Call resolution:** Uses progressive prefix stripping to match calls like `package.subpackage.module.function` to the graph node `module.function`.

### 4. Symbol Matching & Ranking

**Module:** `indexer/symbol_extractor.py`

```python
symbol_extractor(query: str, parsed_json: str) -> dict
```

Matches a query string against symbol names using token-based substring matching:
1. Tokenizes the query — splits on non-alphanumeric characters and CamelCase boundaries
2. Tokenizes each symbol name the same way
3. Returns files containing symbols where query tokens overlap with symbol tokens

**Module:** `intelligence/rank_graph_connections.py`

```python
rank_graph_nodes(graph, start_nodes, max_nodes=40, return_scores=False) -> list
```

Ranks all reachable nodes from the matched symbols using a composite score:

```
score = (1 / (distance + 1)) + pagerank + degree * 0.01
```

- **Distance** — shortest path from any start node (BFS, max depth 4)
- **PageRank** — NetworkX PageRank (alpha=0.85) on the full graph
- **Degree** — node connectivity, weighted at 0.01

### 5. Connection Traversal

**Module:** `graph_builder/symbols_connections.py`

```python
generate_complete_connections(
    symbol_list: list,
    graph: nx.DiGraph,
    depth: int = 2,
    max_nodes: int = None,
    rank_keep_pct: float = 1.0,
    return_ranked: bool = False,
    return_scores: bool = False,
) -> list | tuple
```

Performs BFS from matched symbols to a specified depth, collecting all incoming and outgoing edges. Optionally filters to the top N% of ranked nodes.

Returns a list of connection dicts:

```python
{"from": "auth.login_user", "to": "auth.audit_login", "type": "calls", "depth": 1}
```

---

## CLI Reference

All commands are available via the `scrooge` entry point after installation.

### `scrooge index <path>`

Indexes the full repository and writes the parsed structure + graph to `output/graph_output.json`.

### `scrooge architecture <path> <query>`

Finds candidate files relevant to a query, ranked by relevance with their call connections.

| Option | Default | Description |
|--------|---------|-------------|
| `--rank-keep-pct` | 0.3 | Fraction (0-1) of top-ranked nodes to keep |
| `--file-keep-pct` | 0.35 | Fraction (0-1) of top-ranked files to keep |

**Output format:**

```json
{
    "candidates": [
        {
            "file": "auth.py",
            "relevance": 100,
            "calls": ["auth.audit_login"],
            "called_by": ["workflow.run_user_onboarding"]
        }
    ],
    "related_files": ["utils.py"]
}
```

- `candidates` — files with connections, sorted by relevance (0-100)
- `calls` — symbols this file's functions call
- `called_by` — symbols that call into this file
- `related_files` — matched files with no direct connections (isolated)

**Filtering pipeline:**
1. Scan repo, skip test/benchmark/migration directories
2. Match query against symbols
3. Build call graph, rank all nodes
4. Keep top `rank_keep_pct` of ranked nodes
5. Map nodes back to files
6. Cross-filter: only files with nodes in the call graph
7. Score each file (max node score), normalize 0-100
8. Split into connected vs isolated
9. Keep top `file_keep_pct` of connected files

### `scrooge connections <path> <query> [depth]`

Traces call paths around matched symbols.

| Option | Default | Description |
|--------|---------|-------------|
| `depth` | 2 | How many levels of connections to traverse |
| `--compact` | false | Compact output for fewer tokens |
| `--rank-keep-pct` | 1.0 | Fraction of ranked nodes to keep |

**Standard output:**

```json
{
    "matched_nodes": ["auth.login_user"],
    "ranked_nodes": ["auth.login_user", "auth.audit_login", "utils.normalize_username"],
    "connections": [
        {"from": "auth.login_user", "to": "auth.audit_login", "type": "calls", "depth": 1}
    ]
}
```

**Compact output** (`--compact`):

```json
{
    "n": ["auth.login_user"],
    "rn": ["auth.login_user", "auth.audit_login"],
    "e": [["auth.login_user", "auth.audit_login", 1]]
}
```

---

## MCP Server Reference

The MCP server exposes the same three commands as tools for AI agents. It runs over stdio using the [Model Context Protocol](https://modelcontextprotocol.io).

### Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `index` | `path` | Full repo index (parsed structure + graph) |
| `architecture` | `path`, `query`, `rank_keep_pct?`, `file_keep_pct?` | Candidate files with connections |
| `connections` | `path`, `query`, `depth?`, `compact?` | Call graph around matched symbols |

### Keyword Extraction

The MCP tool descriptions instruct AI agents to **extract keywords** from the user's natural-language question before calling Scrooge. This is critical for good results because Scrooge matches by substring against code identifiers.

The tool descriptions include a blacklist of generic programming words (function, method, class, handler, etc.) that agents should remove from queries before passing them.

### Architecture Output File

The `architecture` tool writes its output to `.scrooge_architecture.json` in the target repo root. This allows agents to re-read the result without calling the tool again.

---

## Project Structure

```
Scrooge/
├── scanner/
│   └── scanner.py               # find source files in a repo
├── parser/
│   └── ast_parser.py            # Python AST → functions, classes, calls
├── indexer/
│   └── symbol_extractor.py      # match query tokens to symbol names
├── graph_builder/
│   ├── call_graph.py            # build NetworkX directed call graph
│   └── symbols_connections.py   # BFS traversal + connection output
├── intelligence/
│   └── rank_graph_connections.py # node ranking (PageRank + distance)
├── output/
│   └── output_writer.py         # JSON serialization for index command
├── cli/
│   └── scrooge_cli.py           # Typer CLI (scrooge command)
├── mcp_server/
│   └── scrooge_mcp.py           # MCP server (scrooge-mcp command)
├── example_repo/                # small test repo for manual testing
├── pyproject.toml               # package metadata + entry points
└── README.md                    # installation + quick start
```

---

## Extending Scrooge

### Adding a New Language Parser

1. Create a parser function that returns the same dict format as `parse_file()`:

```python
{
    "files": {
        "filename.ext": {
            "functions": {
                "func_name": {"calls": ["module.other_func"]}
            },
            "classes": {
                "ClassName": {
                    "methods": {
                        "method_name": {"calls": [...]}
                    }
                }
            }
        }
    }
}
```

2. Add the file extension to `scanner/scanner.py` (line 4)
3. Add a dispatch condition in the CLI and MCP server where `file.suffix == ".py"` is checked

### Adding a New Command

1. Add a `@app.command()` function in `cli/scrooge_cli.py`
2. Add a matching tool definition in `mcp_server/scrooge_mcp.py` (both `list_tools` and `call_tool`)

### Tuning the Ranking Algorithm

The ranking formula in `intelligence/rank_graph_connections.py` uses three signals:

| Signal | Weight | Purpose |
|--------|--------|---------|
| `1 / (distance + 1)` | Primary | Closer nodes score higher |
| `pagerank` | Secondary | Structurally important nodes score higher |
| `degree * 0.01` | Tertiary | Well-connected nodes get a small boost |

You can adjust these weights or add new signals (e.g., file size, recency of changes) in `rank_graph_nodes()`.

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `networkx` | >=3.2 | Graph data structure, PageRank, BFS |
| `mcp` | >=1.26 | Model Context Protocol server |
| `typer` | >=0.12 | CLI framework |
