import json
import math
import re
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
def architecture(
    path: str,
    query: str = typer.Argument(""),
    rank_keep_pct: float = typer.Option(
        0.3,
        "--rank-keep-pct",
        help="Percentuale (0-1) dei nodi rankati da mantenere per connections.",
    ),
    file_keep_pct: float = typer.Option(
        0.35,
        "--file-keep-pct",
        help="Percentuale (0-1) dei file rankati da mantenere dopo lo scoring.",
    ),
):
    files = scan_repo(path)
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
    symbol_map = symbol_extractor(query, parsed_payload)

    arch_files_raw = list(symbol_map.keys())
    matched_nodes = sorted(set(_symbol_map_to_nodes(symbol_map)))
    symbol_list = [{"name": node, "type": "function"} for node in matched_nodes]

    # BFS runs on the full ranked graph (rank_keep_pct=1.0) so start_nodes are reachable
    connections_list, ranked_nodes, node_scores = generate_complete_connections(
        symbol_list,
        graph,
        depth=2,
        rank_keep_pct=1.0,
        return_scores=True,
    )

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
    if isinstance(file_keep_pct, (int, float)) and 0 < file_keep_pct < 1:
        keep_count = max(1, math.ceil(len(connected) * file_keep_pct))
        connected = connected[:keep_count]

    json_output = {
        "candidates": connected,
    }
    if isolated:
        json_output["related_files"] = isolated
    typer.echo(json.dumps(json_output, indent=2, ensure_ascii=False))


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
