"""Diagnostic script to understand why specific test cases fail."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scanner.scanner import scan_repo
from parser.ast_parser import parse_file
from graph_builder.call_graph import build_graph
from indexer.symbol_extractor import symbol_extractor
import re

_NON_ARCH_PATTERNS = re.compile(
    r"([\\/]tests?[\\/]|[\\/]benchmarks?[\\/]|[\\/]fixtures?[\\/]"
    r"|[\\/]migrations?[\\/]|[\\/]examples?[\\/]|[/\\]conftest\.py$"
    r"|(?:^|[\\/])test_[^/\\]*\.py$|_test\.py$)"
)

desktop = Path("C:/Users/ssamu/OneDrive/Desktop")

CASES = [
    (str(desktop / "Scrooge"), "rank pagerank", "rank_graph_connections.py"),
    (str(desktop / "brian2tools/brian2tools"), "synapse plot", "synapses.py"),
    (str(desktop / "brian2tools/brian2tools"), "lems export nml", "lemsexport.py"),
    (str(desktop / "github-biran2/brian2"), "neuron group equations", "neurongroup.py"),
]

for repo_path, query, target_file in CASES:
    print(f"\n{'='*60}")
    print(f"REPO: {Path(repo_path).name}  QUERY: '{query}'  TARGET: {target_file}")
    print(f"{'='*60}")

    files = scan_repo(repo_path)
    parsed_repo = {"files": {}}
    name_to_path = {}

    for file in files:
        if file.suffix == ".py":
            name_to_path.setdefault(file.name, []).append(str(file))
            if not _NON_ARCH_PATTERNS.search(str(file).replace("\\", "/")):
                parsed_file = parse_file(file)
                parsed_repo["files"].update(parsed_file.get("files", {}))

    graph = build_graph(parsed_repo)

    # Check if target file is in parsed repo
    target_in_parsed = target_file in parsed_repo["files"]
    print(f"Target '{target_file}' in parsed_repo: {target_in_parsed}")
    if target_in_parsed:
        file_data = parsed_repo["files"][target_file]
        print(f"  Functions: {list(file_data.get('functions', {}).keys())[:5]}")
        print(f"  Classes: {list(file_data.get('classes', {}).keys())[:3]}")

    # Check symbol extractor
    parsed_payload = json.dumps({"parsed_repo": parsed_repo})
    symbol_map = symbol_extractor(query, parsed_payload)
    target_matched = target_file in symbol_map
    print(f"Target '{target_file}' matched by symbol_extractor: {target_matched}")
    if symbol_map:
        print(f"  Files matched by symbol_extractor: {list(symbol_map.keys())[:8]}")
    else:
        print(f"  NO files matched!")

    # Check graph nodes for target
    stem = Path(target_file).stem
    target_nodes = [n for n in graph.nodes() if n.startswith(stem + ".")]
    print(f"Graph nodes for '{stem}.*': {target_nodes[:6]}")
    if target_nodes:
        for n in target_nodes[:3]:
            in_edges = list(graph.in_edges(n))
            out_edges = list(graph.out_edges(n))
            print(f"  {n}: {len(out_edges)} calls, {len(in_edges)} called_by")
