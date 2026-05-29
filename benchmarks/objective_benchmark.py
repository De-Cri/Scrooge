"""
Objective benchmark for Scrooge vs. grep-based baseline.

Measures:
  - Hit@1  : expected file is the first candidate
  - Hit@3  : expected file is in the top 3 candidates
  - Hit@All: expected file appears anywhere in candidates
  - Precision: fraction of returned files that are expected (for the test case)
  - Candidate count: how many files Scrooge returned
  - Baseline files: how many files grep would return (raw text match)
  - Reduction ratio: baseline_count / scrooge_count  (higher = more filtering)
  - Token estimate: rough estimate of tokens in Scrooge output JSON

Usage:
    python benchmarks/objective_benchmark.py
"""

import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scanner.scanner import scan_repo
from parser.ast_parser import parse_file
from graph_builder.call_graph import build_graph
from graph_builder.symbols_connections import generate_complete_connections
from indexer.symbol_extractor import symbol_extractor
import math

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


def run_scrooge_architecture(repo_path: str, query: str, rank_keep_pct=0.3, file_keep_pct=0.35):
    """Run the full Scrooge architecture pipeline. Returns (candidates, elapsed_seconds)."""
    t0 = time.perf_counter()

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
    parsed_payload = json.dumps({"parsed_repo": parsed_repo})
    symbol_map = symbol_extractor(query, parsed_payload)

    arch_files_raw = list(symbol_map.keys())
    matched_nodes = sorted(set(_symbol_map_to_nodes(symbol_map)))
    symbol_list = [{"name": node, "type": "function"} for node in matched_nodes]

    matched_nodes_by_file = {}
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
        matched_nodes_by_file.setdefault(file_name, []).append({"symbol": symbol_label, "line": line})

    if not symbol_list:
        return [], time.perf_counter() - t0

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

    # Do NOT drop files that have no connection edges — they may be isolated
    # terminal modules that are exactly what the query targets.
    # We keep them so the relevance score (graph + token coverage) determines ranking.

    candidate_stems = {Path(f).stem for f in important_files}
    scoped_connections = [
        item for item in ordered_connections
        if item.get("from", "").split(".")[0] in candidate_stems
        and item.get("to", "").split(".")[0] in candidate_stems
    ]

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

    file_summaries = []
    for f in important_files:
        file_basename = Path(f).name
        matches = matched_nodes_by_file.get(file_basename, [])
        stem = Path(f).stem
        file_matched_nodes = {f"{stem}.{m['symbol']}" for m in matches}

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

    connected = [f for f in file_summaries if f["matches"]]
    connected.sort(key=lambda x: x["relevance"], reverse=True)

    if isinstance(file_keep_pct, (int, float)) and 0 < file_keep_pct < 1:
        keep_count = max(1, math.ceil(len(connected) * file_keep_pct))
        connected = connected[:keep_count]

    return connected, time.perf_counter() - t0


def grep_baseline(repo_path: str, query: str):
    """Simple grep baseline: find all .py files containing any query token."""
    tokens = [t.lower() for t in re.split(r"\s+", query.strip()) if t]
    files = scan_repo(repo_path)
    matched = []
    for f in files:
        if f.suffix != ".py":
            continue
        if _NON_ARCH_PATTERNS.search(str(f).replace("\\", "/")):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace").lower()
            if any(tok in content for tok in tokens):
                matched.append(str(f))
        except Exception:
            pass
    return matched


def estimate_tokens(candidates: list) -> int:
    """Rough token count: ~4 chars per token for the JSON output."""
    return max(1, len(json.dumps(candidates)) // 4)


def estimate_grep_tokens(files: list, repo_path: str) -> int:
    """Tokens if the agent reads ALL matched files fully."""
    total_chars = 0
    for f in files:
        try:
            total_chars += len(Path(f).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return max(1, total_chars // 4)


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

def make_test_suite():
    """
    Returns a list of test cases:
        {
            "repo": absolute path to repo,
            "query": keyword query string,
            "expected_basenames": list of filename basenames that MUST appear in candidates,
            "description": human-readable what the test checks
        }
    """
    desktop = Path("C:/Users/ssamu/OneDrive/Desktop")
    scrooge = str(desktop / "Scrooge")
    brian2tools = str(desktop / "brian2tools" / "brian2tools")
    brian2 = str(desktop / "github-biran2" / "brian2")

    cases = [
        # ------------------------------------------------------------------ Scrooge (small, ground truth known)
        {
            "repo": scrooge,
            "query": "call graph build",
            "expected_basenames": ["call_graph.py"],
            "description": "Scrooge: graph builder module"
        },
        {
            "repo": scrooge,
            "query": "symbol extract tokenize",
            "expected_basenames": ["symbol_extractor.py"],
            "description": "Scrooge: symbol extractor module"
        },
        {
            "repo": scrooge,
            "query": "rank pagerank",
            "expected_basenames": ["rank_graph_connections.py"],
            "description": "Scrooge: ranking/intelligence module"
        },
        {
            "repo": scrooge,
            "query": "parse ast import",
            "expected_basenames": ["ast_parser.py"],
            "description": "Scrooge: AST parser module"
        },
        {
            "repo": scrooge,
            "query": "scan repo",
            "expected_basenames": ["scanner.py"],
            "description": "Scrooge: scanner module"
        },
        {
            "repo": scrooge,
            "query": "connections depth bfs",
            "expected_basenames": ["symbols_connections.py"],
            "description": "Scrooge: connection traversal"
        },

        # ------------------------------------------------------------------ brian2tools (medium, 37 files)
        {
            "repo": brian2tools,
            "query": "morphology plot",
            "expected_basenames": ["morphology.py"],
            "description": "brian2tools: morphology plotting"
        },
        {
            "repo": brian2tools,
            "query": "synapse plot",
            "expected_basenames": ["synapses.py"],
            "description": "brian2tools: synapse plotting"
        },
        {
            "repo": brian2tools,
            "query": "lems export nml",
            "expected_basenames": ["lemsexport.py"],
            "description": "brian2tools: LEMS/NML export"
        },
        {
            "repo": brian2tools,
            "query": "collector device export",
            "expected_basenames": ["collector.py"],
            "description": "brian2tools: base export collector"
        },
        {
            "repo": brian2tools,
            "query": "md export expander",
            "expected_basenames": ["mdexporter.py", "expander.py"],
            "description": "brian2tools: markdown exporter"
        },

        # ------------------------------------------------------------------ brian2 (large, 5000+ files)
        {
            "repo": brian2,
            "query": "neuron group equations",
            "expected_basenames": ["neurongroup.py"],
            "description": "brian2: NeuronGroup class"
        },
        {
            "repo": brian2,
            "query": "synapse connect",
            "expected_basenames": ["synapses.py"],
            "description": "brian2: Synapses connection"
        },
        {
            "repo": brian2,
            "query": "network run simulation",
            "expected_basenames": ["network.py"],
            "description": "brian2: Network run loop"
        },
        {
            "repo": brian2,
            "query": "codegen translation generate",
            "expected_basenames": ["translation.py"],
            "description": "brian2: code generation translation"
        },
        {
            "repo": brian2,
            "query": "preferences prefs store",
            "expected_basenames": ["preferences.py"],
            "description": "brian2: preferences system"
        },
    ]

    return cases


def run_benchmark():
    cases = make_test_suite()
    results = []
    repo_timings = {}

    print("\n" + "="*80)
    print("SCROOGE OBJECTIVE BENCHMARK")
    print("="*80)
    print(f"{'#':<3} {'Description':<45} {'Hit@1':<6} {'Hit@3':<6} {'Hit@All':<8} {'Prec':<6} {'Cands':<6} {'Grep':<6} {'Reduce':<8} {'Time':<6}")
    print("-"*80)

    for i, case in enumerate(cases, 1):
        repo = case["repo"]
        query = case["query"]
        expected = set(case["expected_basenames"])
        desc = case["description"]

        try:
            candidates, elapsed = run_scrooge_architecture(repo, query)
        except Exception as e:
            print(f"{i:<3} {desc:<45} ERROR: {e}")
            continue

        candidate_basenames = [Path(c["file"]).name for c in candidates]
        candidate_set = set(candidate_basenames)

        hit_at_1 = bool(candidates) and Path(candidates[0]["file"]).name in expected
        hit_at_3 = any(Path(c["file"]).name in expected for c in candidates[:3])
        hit_at_all = bool(expected & candidate_set)

        # Precision: among returned files, how many are in expected?
        # For cases with 1 expected file, precision = 1/N if hit
        precision = (
            len(expected & candidate_set) / len(candidate_set)
            if candidate_set else 0.0
        )

        # Grep baseline
        grep_files = grep_baseline(repo, query)
        reduction = len(grep_files) / max(1, len(candidates))

        result = {
            "case": i,
            "description": desc,
            "repo": Path(repo).name,
            "query": query,
            "expected": sorted(expected),
            "candidates": candidate_basenames,
            "hit_at_1": hit_at_1,
            "hit_at_3": hit_at_3,
            "hit_at_all": hit_at_all,
            "precision": round(precision, 3),
            "candidate_count": len(candidates),
            "grep_count": len(grep_files),
            "reduction_ratio": round(reduction, 1),
            "elapsed_s": round(elapsed, 2),
        }
        results.append(result)

        h1 = "YES" if hit_at_1 else "NO "
        h3 = "YES" if hit_at_3 else "NO "
        ha = "YES" if hit_at_all else "NO "
        print(f"{i:<3} {desc:<45} {h1:<6} {h3:<6} {ha:<8} {precision:<6.2f} {len(candidates):<6} {len(grep_files):<6} {reduction:<8.1f} {elapsed:.1f}s")

    # Summary
    total = len(results)
    if total == 0:
        print("No results.")
        return

    hit1 = sum(1 for r in results if r["hit_at_1"])
    hit3 = sum(1 for r in results if r["hit_at_3"])
    hitall = sum(1 for r in results if r["hit_at_all"])
    avg_prec = sum(r["precision"] for r in results) / total
    avg_cands = sum(r["candidate_count"] for r in results) / total
    avg_grep = sum(r["grep_count"] for r in results) / total
    avg_reduce = sum(r["reduction_ratio"] for r in results) / total
    avg_time = sum(r["elapsed_s"] for r in results) / total

    scrooge_cases = [r for r in results if r["repo"] == "Scrooge"]
    brian2tools_cases = [r for r in results if r["repo"] == "brian2tools"]
    brian2_cases = [r for r in results if r["repo"] == "brian2"]

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total cases : {total}")
    print(f"Hit@1       : {hit1}/{total} ({100*hit1/total:.0f}%)")
    print(f"Hit@3       : {hit3}/{total} ({100*hit3/total:.0f}%)")
    print(f"Hit@All     : {hitall}/{total} ({100*hitall/total:.0f}%)")
    print(f"Avg Precision: {avg_prec:.2f}")
    print(f"Avg candidates returned : {avg_cands:.1f}")
    print(f"Avg grep matches (baseline) : {avg_grep:.1f}")
    print(f"Avg file reduction (grep/scrooge): {avg_reduce:.1f}x")
    print(f"Avg query time : {avg_time:.1f}s")

    for label, group in [("Scrooge (small, 24 files)", scrooge_cases),
                         ("brian2tools (medium, 37 files)", brian2tools_cases),
                         ("brian2 (large, 5000+ files)", brian2_cases)]:
        if not group:
            continue
        g_hit1 = sum(1 for r in group if r["hit_at_1"])
        g_hitall = sum(1 for r in group if r["hit_at_all"])
        g_prec = sum(r["precision"] for r in group) / len(group)
        g_reduce = sum(r["reduction_ratio"] for r in group) / len(group)
        g_time = sum(r["elapsed_s"] for r in group) / len(group)
        print(f"\n  {label}")
        print(f"    Hit@1={g_hit1}/{len(group)} HitAll={g_hitall}/{len(group)} AvgPrec={g_prec:.2f} AvgReduce={g_reduce:.1f}x AvgTime={g_time:.1f}s")

    # Save full results
    out_path = Path(__file__).parent / "benchmark_results_objective.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nFull results saved to: {out_path}")
    return results


if __name__ == "__main__":
    run_benchmark()
