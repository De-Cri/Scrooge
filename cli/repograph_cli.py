import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import typer
from scanner.scanner import scan_repo
from parser.ast_parser import parse_file
from graph_builder.call_graph import build_graph
from graph_builder.symbols_connections import generate_complete_connections
from indexer.symbol_extractor import symbol_extractor
from output.output_writer import write_run_output

app = typer.Typer()

def _build_parsed_repo(path: str):
    files = scan_repo(path)
    parsed_repo = {"files": {}}

    for file in files:
        if file.suffix == ".py":
            parsed_file = parse_file(file)
            parsed_repo["files"].update(parsed_file.get("files", {}))

    return parsed_repo

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

@app.command()
def index(path: str):
    parsed_repo = _build_parsed_repo(path)
    graph = build_graph(parsed_repo)
    output_path = write_run_output(parsed_repo, graph)
    typer.echo(f"Output scritto in: {output_path}")

@app.command()
def architecture(path: str, query: str = typer.Argument("")):
    parsed_repo = _build_parsed_repo(path)
    parsed_payload = json.dumps({"parsed_repo": parsed_repo})
    result = symbol_extractor(query, parsed_payload)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command()
def connections(
    path: str,
    query: str = typer.Argument(""),
    depth: int = typer.Argument(2),
    compact: bool = typer.Option(False, "--compact", help="Output compatto per ridurre i token."),
    rank_keep_pct: float = typer.Option(
        1.0,
        "--rank-keep-pct",
        help="Percentuale (0-1) dei nodi rankati da mantenere.",
    ),
):
    parsed_repo = _build_parsed_repo(path)
    graph = build_graph(parsed_repo)
    parsed_payload = json.dumps({"parsed_repo": parsed_repo})
    symbol_map = symbol_extractor(query, parsed_payload)
    matched_nodes = sorted(set(_symbol_map_to_nodes(symbol_map)))
    symbol_list = [{"name": node, "type": "function"} for node in matched_nodes]
    connections_list, ranked_nodes = generate_complete_connections(
        symbol_list,
        graph,
        depth=depth,
        rank_keep_pct=rank_keep_pct,
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
    if compact:
        payload = {
            "n": matched_nodes,
            "rn": ranked_nodes,
            "e": [
                [item.get("from"), item.get("to"), item.get("depth", 0)]
                for item in ordered_connections
            ],
        }
    else:
        payload = {
            "matched_nodes": matched_nodes,
            "ranked_nodes": ranked_nodes,
            "connections": ordered_connections,
        }
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
