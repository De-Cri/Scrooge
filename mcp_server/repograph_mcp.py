from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import asyncio
import json
import math
import re
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


# TODO: _symbol_map_to_nodes is duplicated in cli/repograph_cli.py — move to a shared utils module when the project grows
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


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "index":
        files = scan_repo(arguments.get("path"))
        parsed_repo = {"files": {}}

        for file in files:
            if file.suffix == ".py":
                parsed_file = parse_file(file)
                parsed_repo["files"].update(parsed_file.get("files", {}))
        graph = build_graph(parsed_repo)

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
        files = scan_repo(arguments.get("path"))
        parsed_repo = {"files": {}}
        name_to_path = {}

        for file in files:
            if file.suffix == ".py":
                name_to_path.setdefault(file.name, []).append(str(file))
                if not _NON_ARCH_PATTERNS.search(str(file).replace("\\", "/")):
                    parsed_file = parse_file(file)
                    parsed_repo["files"].update(parsed_file.get("files", {}))

        graph = build_graph(parsed_repo)
        parsed_payload = json.dumps({"parsed_repo": parsed_repo})
        symbol_map = symbol_extractor(arguments.get("query"), parsed_payload)

        arch_files_raw = list(symbol_map.keys())
        matched_nodes = sorted(set(_symbol_map_to_nodes(symbol_map)))
        symbol_list = [{"name": node, "type": "function"} for node in matched_nodes]

        # BFS runs on the full ranked graph (rank_keep_pct=1.0) so start_nodes are
        # always reachable — mirrors the CLI connections flow that produced the benchmark results.
        # rank_keep_pct from the caller is applied AFTER to filter important_files only.
        rank_keep_pct = arguments.get("rank_keep_pct", 0.3)
        connections_list, ranked_nodes, node_scores = generate_complete_connections(
            symbol_list,
            graph,
            depth=2,
            rank_keep_pct=1.0,
            return_scores=True,
        )

        # important_files: arch files whose module appears in the top rank_keep_pct of ranked nodes
        # (mirrors benchmark arch_filter="connections" logic)
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

        # deduplicazione per (from, to) — self-loop rimossi
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

        all_nodes = sorted({n for item in ordered_connections for n in (item.get("from"), item.get("to")) if n})

        # Cross-filter: keep only files that have at least one node in the call_graph
        graph_modules = {node.split(".")[0] + ".py" for node in all_nodes if "." in node}
        important_files = [f for f in important_files if Path(f).name in graph_modules]

        # Scope call_graph to only candidate file modules
        candidate_stems = {Path(f).stem for f in important_files}
        scoped_connections = [
            item for item in ordered_connections
            if item.get("from", "").split(".")[0] in candidate_stems
            and item.get("to", "").split(".")[0] in candidate_stems
        ]
        scoped_nodes = sorted({n for item in scoped_connections for n in (item.get("from"), item.get("to")) if n})

        # Compute per-file relevance score (max node score per file, normalized 0-100)
        file_scores = {}
        for f in important_files:
            prefix = Path(f).stem + "."
            max_score = max(
                (node_scores.get(n, 0) for n in node_scores if n.startswith(prefix)),
                default=0,
            )
            file_scores[f] = max_score

        top_score = max(file_scores.values(), default=1) or 1

        # Build per-file connection summary for agent file picking
        file_summaries = []
        for f in important_files:
            prefix = Path(f).stem + "."
            calls_out = set()
            called_by = set()
            for edge in scoped_connections:
                frm, to = edge.get("from", ""), edge.get("to", "")
                if frm.startswith(prefix):
                    calls_out.add(to)
                if to.startswith(prefix):
                    called_by.add(frm)
            file_summaries.append({
                "file": f,
                "relevance": round(file_scores[f] / top_score * 100),
                "calls": sorted(calls_out),
                "called_by": sorted(called_by),
            })

        # Split: candidates with connections vs isolated files (no calls and no called_by)
        connected = [f for f in file_summaries if f["calls"] or f["called_by"]]
        isolated = [f["file"] for f in file_summaries if not f["calls"] and not f["called_by"]]

        connected.sort(key=lambda x: x["relevance"], reverse=True)
        file_keep_pct = arguments.get("file_keep_pct", 0.35)
        if isinstance(file_keep_pct, (int, float)) and 0 < file_keep_pct < 1:
            keep_count = max(1, math.ceil(len(connected) * file_keep_pct))
            connected = connected[:keep_count]

        json_output = {
            "candidates": connected,
        }
        if isolated:
            json_output["related_files"] = isolated
        # Write output to a file so the agent can consult it as dynamic memory
        repo_path = Path(arguments.get("path"))
        output_file = repo_path / ".scrooge_architecture.json"
        output_file.write_text(json.dumps(json_output, indent=2), encoding="utf-8")

        return [types.TextContent(type="text", text=f"Architecture saved to {output_file}. Read that file to see candidates and call graph.")]

    if name == "connections":
        files = scan_repo(arguments.get("path"))
        parsed_repo = {"files": {}}
        for file in files:
            if file.suffix == ".py":
                parsed_file = parse_file(file)
                parsed_repo["files"].update(parsed_file.get("files", {}))
        graph = build_graph(parsed_repo)
        parsed_payload = json.dumps({"parsed_repo": parsed_repo})
        symbol_map = symbol_extractor(arguments.get("query"), parsed_payload)
        matched_nodes = sorted(set(_symbol_map_to_nodes(symbol_map)))
        symbol_list = [{"name": node, "type": "function"} for node in matched_nodes]
        connections_list, ranked_nodes = generate_complete_connections(
            symbol_list,
            graph,
            depth=arguments.get("depth", 2),
            return_ranked=True,
        )
        unique_connections = set()
        ordered_connections = []
        for item in connections_list:
            frm, to = item.get("from"), item.get("to")
            if frm == to:  # Fix A: rimuovi self-loop
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
        
asyncio.run(main())
