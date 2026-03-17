from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import asyncio
import json
from graph_builder.call_graph import build_graph
from graph_builder.symbols_connections import generate_complete_connections
from pathlib import Path
from indexer.symbol_extractor import symbol_extractor
from parser.ast_parser import parse_file
from scanner.scanner import scan_repo

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
            description="given a file-path and a query, scans the entire folder, parses the folder's structure, returns only the relevant parts of the parsed repo",
            inputSchema={
                "type":"object",
                "properties": {
                    "path":{
                        "type":"string",
                        "description":"represents the path of the folder to parse"
                    },
                    "query":{
                        "type":"string",
                        "description":"represents the query given from the user"
                    }
                },
                "required":["path","query"]
            }
        ),
        types.Tool(
            name="connections",
            description="given a repo path and a query, returns the call graph connections between the symbols relevant to the query, with optional depth control and compact output",
            inputSchema={
                "type":"object",
                "properties": {
                    "path":{
                        "type":"string",
                        "description":"represents the path of the folder to parse"
                    },
                    "query":{
                        "type":"string",
                        "description":"represents the query given from the user"
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

        for file in files:
            if file.suffix == ".py":
                parsed_file = parse_file(file)
                parsed_repo["files"].update(parsed_file.get("files", {}))
        parsed_payload = json.dumps({"parsed_repo": parsed_repo})
        
        json_output = symbol_extractor(arguments.get("query"), parsed_payload)
        result = json.dumps(json_output)
        return [types.TextContent(type="text", text=result)]

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
            key = (item.get("from"), item.get("to"), item.get("depth"))
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