from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import asyncio
import functools
import json
import math
import re
import sys
from graph_builder.call_graph import build_graph
from graph_builder.symbols_connections import generate_complete_connections
from pathlib import Path
from indexer.symbol_extractor import symbol_extractor
from parser.ast_parser import parse_file
from scanner.scanner import scan_repo

_NON_ARCH_PATTERNS = re.compile(
    r"([\\/]tests?[\\/]"
    r"|[\\/]benchmarks?[\\/]"
    r"|[\\/]fixtures?[\\/]"
    r"|[\\/]migrations?[\\/]"
    r"|[\\/]examples?[\\/]"
    r"|[/\\]conftest\.py$"
    r"|(?:^|[\\/])test_[^/\\]*\.py$"
    r"|_test\.py$)"
)

app = Server("Scrooge")
#This is the coding agent's interface
@app.list_tools()
async def list_tools():
    return[
        types.Tool(
            name="index",
            description="given a file-path ,scans the entire folder and returns the full parsed structure of the repository and a connection graph",
            inputSchema={
                "type": "object",
                "properties": {
                    "path":{
                        "type":"string",
                        "description": "represents the path of the folder you want to parse"
                    }
                },
                "required":["path"]
            }
        ),
        types.Tool(
            name="architecture",
            description="given a file-path and a keyword query, scans the entire folder and returns candidate files with their connections (calls/called_by) and a scoped call graph. The result is also saved to '.scrooge_architecture.json' in the repo root — re-read that file whenever you need to recall how modules are connected instead of calling this tool again. IMPORTANT: do NOT open all candidates — study the 'calls' and 'called_by' fields to understand how files relate to each other, then select only the most relevant ones to inspect based on the connections. QUERY INSTRUCTIONS: Do NOT pass the user's raw question. Instead, extract keywords that match likely symbol names (function names, class names, method names, file names) in the codebase. Scrooge matches by substring against identifiers — so use short, specific terms like 'auth login user' instead of 'how does the authentication flow work'. Think about what the relevant code symbols might be named and use those words. IMPORTANT: Before passing the query, REMOVE all generic programming words that would cause false positives. Drop any of these from the query: function, method, class, module, file, variable, parameter, argument, object, instance, attribute, property, type, return, import, def, self, init, constructor, decorator, lambda, callback, handler, helper, utility, base, abstract, interface, mixin, enum, struct, schema, model, config, setup, factory, builder, manager, service, controller, provider, wrapper, middleware. Do NOT add new words — only remove superfluous ones from the user's query and keep the domain-specific terms.",
            inputSchema={
                "type":"object",
                "properties": {
                    "path":{
                        "type":"string",
                        "description":"represents the path of the folder to parse"
                    },
                    "query":{
                        "type":"string",
                        "description":"space-separated keywords extracted from the user's question. Remove generic programming words (function, method, class, module, variable, handler, etc.) before passing — only keep domain-specific terms."
                    },
                    "rank_keep_pct":{
                        "type":"number",
                        "description":"fraction (0-1) of top-ranked connection nodes to keep when filtering important files (default 0.3)"
                    },
                    "file_keep_pct":{
                        "type":"number",
                        "description":"fraction (0-1) of top-ranked files to keep after relevance scoring (default 0.35)"
                    }
                },
                "required":["path","query"]
            }
        ),
        types.Tool(
            name="connections",
            description="given a repo path and a keyword query, returns the call graph connections between the symbols relevant to the query, with optional depth control and compact output. QUERY INSTRUCTIONS: Do NOT pass the user's raw question. Instead, extract keywords that match likely symbol names (function names, class names, method names, file names). Scrooge matches by substring against identifiers — use short, specific terms. IMPORTANT: Before passing the query, REMOVE all generic programming words that would cause false positives. Drop any of these from the query: function, method, class, module, file, variable, parameter, argument, object, instance, attribute, property, type, return, import, def, self, init, constructor, decorator, lambda, callback, handler, helper, utility, base, abstract, interface, mixin, enum, struct, schema, model, config, setup, factory, builder, manager, service, controller, provider, wrapper, middleware. Do NOT add new words — only remove superfluous ones and keep domain-specific terms.",
            inputSchema={
                "type":"object",
                "properties": {
                    "path":{
                        "type":"string",
                        "description":"represents the path of the folder to parse"
                    },
                    "query":{
                        "type":"string",
                        "description":"space-separated keywords extracted from the user's question. Remove generic programming words (function, method, class, module, variable, handler, etc.) before passing — only keep domain-specific terms."
                    },
                    "depth":{
                        "type":"integer",
                        "description":"how many levels of connections to traverse (default 2)"
                    },
                    "compact":{
                        "type":"boolean",
                        "description":"if true, returns a compact output to reduce token usage"
                    }
                },
                "required":["path","query"]
            }
        )
    ]


# TODO: _symbol_map_to_nodes is duplicated in cli/scrooge_cli.py — move to a shared utils module when the project grows
def _symbol_map_to_nodes(symbol_map: dict):
    nodes = []
    for file_name, file_data in symbol_map.items():
        module_name = Path(file_name).stem
        for function_name in file_data.get("functions", []):
            nodes.append(f"{module_name}.{function_name}")
        for class_name, class_data in file_data.get("classes", {}).items():
            for method_name in class_data.get("methods", []):
                nodes.append(f"{module_name}.{class_name}.{method_name}")
    return nodes


def _run_index(path: str):
    files = scan_repo(path)
    parsed_repo = {"files": {}}
    for file in files:
        if file.suffix == ".py":
            parsed_file = parse_file(file)
            parsed_repo["files"].update(parsed_file.get("files", {}))
    graph = build_graph(parsed_repo)
    return parsed_repo, graph


def _run_architecture(arguments: dict, progress_fn):
    path = arguments.get("path")
    query = arguments.get("query")
    files = scan_repo(path)
    progress_fn(f"Repo scanned: {len(files)} files found")
    parsed_repo = {"files": {}}
    name_to_path = {}
    for file in files:
        if file.suffix == ".py":
            name_to_path.setdefault(file.name, []).append(str(file))
            if not _NON_ARCH_PATTERNS.search(str(file).replace("\\", "/")):
                parsed_file = parse_file(file)
                parsed_repo["files"].update(parsed_file.get("files", {}))
    progress_fn(f"Parsed {len(parsed_repo['files'])} source files (tests/examples excluded)")
    graph = build_graph(parsed_repo)
    progress_fn(f"Call graph built: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    return parsed_repo, graph, name_to_path


def _run_connections(path: str, query: str, depth: int):
    files = scan_repo(path)
    parsed_repo = {"files": {}}
    for file in files:
        if file.suffix == ".py":
            parsed_file = parse_file(file)
            parsed_repo["files"].update(parsed_file.get("files", {}))
    graph = build_graph(parsed_repo)
    parsed_payload = json.dumps({"parsed_repo": parsed_repo})
    symbol_map = symbol_extractor(query, parsed_payload)
    matched_nodes = sorted(set(_symbol_map_to_nodes(symbol_map)))
    symbol_list = [{"name": node, "type": "function"} for node in matched_nodes]
    connections_list, ranked_nodes = generate_complete_connections(
        symbol_list, graph, depth=depth, return_ranked=True,
    )
    return matched_nodes, connections_list, ranked_nodes


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    loop = asyncio.get_event_loop()

    if name == "index":
        parsed_repo, graph = await loop.run_in_executor(
            None, _run_index, arguments.get("path")
        )

        json_output= {
            "parsed_repo": parsed_repo,
            "graph": {
                "nodes": list(graph.nodes()),
                "edges": [{"source": src, "target": dst} for src, dst in graph.edges()],
            }
        }        
        result=json.dumps(json_output)
        return [types.TextContent(type="text", text=result)]

    if name == "architecture":
        print("[Scrooge] architecture tool called", flush=True, file=sys.stderr)
        _scrooge_output_dir = Path(__file__).parent.parent / "output"
        _scrooge_output_dir.mkdir(exist_ok=True)
        _progress_file = _scrooge_output_dir / "scrooge_progress.log"

        def _progress(msg: str):
            print(f"[Scrooge] {msg}", flush=True, file=sys.stderr)
            with _progress_file.open("a", encoding="utf-8") as _f:
                _f.write(msg + "\n")
                _f.flush()

        _progress_file.write_text("", encoding="utf-8")  # reset log
        _progress(f"Starting architecture scan: {arguments.get('path')} | query: {arguments.get('query')}")

        parsed_repo, graph, name_to_path = await loop.run_in_executor(
            None, functools.partial(_run_architecture, arguments, _progress)
        )
        parsed_payload = json.dumps({"parsed_repo": parsed_repo})
        symbol_map = await loop.run_in_executor(
            None, symbol_extractor, arguments.get("query"), parsed_payload
        )
        _progress(f"Symbol extraction done: {len(symbol_map)} matched files")

        arch_files_raw = list(symbol_map.keys())
        matched_nodes = sorted(set(_symbol_map_to_nodes(symbol_map)))
        symbol_list = [{"name": node, "type": "function"} for node in matched_nodes]

        # Map: file basename -> [{"symbol": "Class.method", "line": N}, ...]
        # for the symbols that actually matched the query.
        matched_nodes_by_file = {}
        matched_node_set = set(matched_nodes)
        for node in matched_nodes:
            if node not in graph:
                continue
            attrs = graph.nodes[node]
            file_name = attrs.get("file")
            line = attrs.get("line")
            if not file_name:
                continue
            parts = node.split(".", 1)
            symbol_label = parts[1] if len(parts) > 1 else node
            matched_nodes_by_file.setdefault(file_name, []).append({
                "symbol": symbol_label,
                "line": line,
            })
        for entries in matched_nodes_by_file.values():
            entries.sort(key=lambda e: (e.get("line") or 0, e.get("symbol") or ""))

        # BFS runs on the full ranked graph (rank_keep_pct=1.0) so start_nodes are
        # always reachable. The caller's rank_keep_pct is applied AFTER, to filter
        # important_files only.
        rank_keep_pct = arguments.get("rank_keep_pct", 0.3)
        connections_list, ranked_nodes, node_scores = await loop.run_in_executor(
            None,
            functools.partial(
                generate_complete_connections,
                symbol_list,
                graph,
                depth=2,
                rank_keep_pct=1.0,
                return_scores=True,
            ),
        )

        # important_files: arch files whose module appears in the top rank_keep_pct of ranked nodes
        if ranked_nodes and 0 < rank_keep_pct < 1:
            keep_count = max(1, math.ceil(len(ranked_nodes) * rank_keep_pct))
            top_ranked = ranked_nodes[:keep_count]
        else:
            top_ranked = ranked_nodes

        conn_modules = {node.split(".")[0] + ".py" for node in top_ranked if "." in node}
        important_files = [
            path
            for f in arch_files_raw
            if f in conn_modules and f in name_to_path
            for path in name_to_path[f]
            if not _NON_ARCH_PATTERNS.search(path.replace("\\", "/"))
        ]

        # deduplicate by (from, to) — remove self-loops
        unique_connections = set()
        ordered_connections = []
        for item in connections_list:
            frm, to = item.get("from"), item.get("to")
            if frm == to:
                continue
            key = (frm, to)
            if key in unique_connections:
                continue
            unique_connections.add(key)
            ordered_connections.append(item)
        ordered_connections.sort(key=lambda c: (c.get("depth", 0), c.get("from", ""), c.get("to", "")))

        # Do NOT cross-filter by graph_modules here — that would drop terminal modules
        # (e.g. a leaf utility file) that matched the query but have no connections
        # to other matched files.  Token coverage + graph score handles ranking instead.

        # Scope call_graph to only candidate file modules
        candidate_stems = {Path(f).stem for f in important_files}
        scoped_connections = [
            item for item in ordered_connections
            if item.get("from", "").split(".")[0] in candidate_stems
            and item.get("to", "").split(".")[0] in candidate_stems
        ]
        scoped_nodes = sorted({n for item in scoped_connections for n in (item.get("from"), item.get("to")) if n})

        # Compute per-file relevance score:
        # 70% graph score (max node score for this file) + 30% token coverage bonus.
        # Token coverage ensures files where MORE query tokens matched rank higher,
        # countering the effect of generic tokens like "plot" or "group" that would
        # otherwise match many unrelated files equally.
        token_coverage = {f: symbol_map.get(Path(f).name, {}).get("_token_coverage", 0.0) for f in important_files}
        file_scores = {}
        for f in important_files:
            prefix = Path(f).stem + "."
            max_graph_score = max(
                (node_scores.get(n, 0) for n in node_scores if n.startswith(prefix)),
                default=0,
            )
            file_scores[f] = max_graph_score * 0.7 + token_coverage.get(f, 0.0) * 0.3

        top_score = max(file_scores.values(), default=1) or 1

        # Build per-file connection summary for agent file picking.
        # `matches` lists the symbols in this file that actually matched the query
        # (with their line numbers, so the agent can Read a precise range).
        # `calls` and `called_by` are scoped to those matched symbols only —
        # not every symbol in the file — so the call graph stays focused.
        file_summaries = []
        for f in important_files:
            file_basename = Path(f).name
            matches = matched_nodes_by_file.get(file_basename, [])

            # Set of qualified node names for THIS file's matched symbols only.
            stem = Path(f).stem
            file_matched_nodes = {
                f"{stem}.{m['symbol']}" for m in matches
            }

            calls_out = set()
            called_by = set()
            for edge in scoped_connections:
                frm, to = edge.get("from", ""), edge.get("to", "")
                if frm in file_matched_nodes:
                    calls_out.add(to)
                if to in file_matched_nodes:
                    called_by.add(frm)

            file_summaries.append({
                "file": f,
                "relevance": round(file_scores[f] / top_score * 100),
                "matches": matches,
                "calls": sorted(calls_out),
                "called_by": sorted(called_by),
            })

        # Keep files that have at least one matched symbol.
        # Files with no internal connections are still returned — they may be
        # leaf modules that are exactly what the query targets (e.g. a utility
        # with no callers in scope yet).  The agent can decide whether to open them.
        connected = [f for f in file_summaries if f["matches"]]

        connected.sort(key=lambda x: x["relevance"], reverse=True)
        file_keep_pct = arguments.get("file_keep_pct", 0.35)
        if isinstance(file_keep_pct, (int, float)) and 0 < file_keep_pct < 1:
            keep_count = max(1, math.ceil(len(connected) * file_keep_pct))
            connected = connected[:keep_count]

        _progress(f"Ranking done: {len(connected)} candidate files kept after filtering")

        json_output = {
            "candidates": connected,
        }

        # Save to scanned repo root (legacy)
        repo_path = Path(arguments.get("path"))
        output_file = repo_path / ".scrooge_architecture.json"
        output_file.write_text(json.dumps(json_output, indent=2), encoding="utf-8")

        # Also save to Scrooge output/ folder with a descriptive name
        repo_name = repo_path.name
        scrooge_out = _scrooge_output_dir / f"{repo_name}_architecture_output.json"
        scrooge_out.write_text(json.dumps(json_output, indent=2), encoding="utf-8")
        _progress(f"Done. Output saved to output/{scrooge_out.name} ({len(connected)} candidates)")

        return [types.TextContent(type="text", text=f"Architecture saved to {output_file} and {scrooge_out}. Read either file to see candidates and call graph.")]

    if name == "connections":
        matched_nodes, connections_list, ranked_nodes = await loop.run_in_executor(
            None, _run_connections,
            arguments.get("path"), arguments.get("query"), arguments.get("depth", 2)
        )
        unique_connections = set()
        ordered_connections = []
        for item in connections_list:
            frm, to = item.get("from"), item.get("to")
            if frm == to:  # skip self-loops
                continue
            key = (frm, to)
            if key in unique_connections:
                continue
            unique_connections.add(key)
            ordered_connections.append(item)
        ordered_connections.sort(key=lambda c: (c.get("depth", 0), c.get("from", ""), c.get("to", "")))
        compact = arguments.get("compact", False)
        if compact:
            payload = {
                "n": matched_nodes,
                "rn": ranked_nodes,
                "e": [[item.get("from"), item.get("to"), item.get("depth", 0)] for item in ordered_connections],
            }
        else:
            payload = {
                "matched_nodes": matched_nodes,
                "ranked_nodes": ranked_nodes,
                "connections": ordered_connections,
            }
        return [types.TextContent(type="text", text=json.dumps(payload))]


async def main():
    async with stdio_server() as (read,write):
        await app.run(read, write, app.create_initialization_options())


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
