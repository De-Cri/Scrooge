import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scanner.scanner import scan_repo
from parser.ast_parser import parse_file
from graph_builder.call_graph import build_graph
from indexer.symbol_extractor import symbol_extractor
from benchmarks.bench_utils import (
    baseline_retrieval,
    build_basename_index,
    files_from_connections,
    resolve_selected_files,
    run_cli_json,
)

READ_WPM = 200
WORDS_PER_LOC = 10
CHARS_PER_TOKEN = 4

def _build_parsed_repo(path: Path):
    files = scan_repo(str(path))
    parsed_repo = {"files": {}}
    for file in files:
        if file.suffix == ".py":
            parsed_file = parse_file(file)
            parsed_repo["files"].update(parsed_file.get("files", {}))
    return parsed_repo


def _flatten_symbol_map(symbol_map):
    nodes = set()
    for file_name, file_data in symbol_map.items():
        module_name = Path(file_name).stem
        for function_name in file_data.get("functions", []):
            nodes.add(f"{module_name}.{function_name}")
        for class_name, class_data in file_data.get("classes", {}).items():
            for method_name in class_data.get("methods", []):
                nodes.add(f"{module_name}.{class_name}.{method_name}")
    return nodes


def _edge_set(graph):
    return {(u, v) for u, v in graph.edges()}


def _load_expected_example():
    expected_path = REPO_ROOT / "benchmarks" / "fixtures" / "expected_example_repo.json"
    raw = expected_path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            data = json.loads(raw.decode(enc))
            break
        except UnicodeDecodeError:
            data = None
    if data is None:
        raise UnicodeError("Unable to decode expected_example_repo.json")
    expected_edges = {(e["source"], e["target"]) for e in data.get("edges", [])}
    return set(data.get("nodes", [])), expected_edges


def _count_loc(files):
    total = 0
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                total += sum(1 for _ in handle)
        except OSError:
            continue
    return total


def _estimate_tokens(text: str):
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def _collect_text_from_files(files):
    chunks = []
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                chunks.append(handle.read())
        except OSError:
            continue
    return "\n".join(chunks)


def benchmark_example_repo_correctness():
    example_repo = REPO_ROOT / "example_repo"
    parsed_repo = _build_parsed_repo(example_repo)
    graph = build_graph(parsed_repo)
    actual_nodes = set(graph.nodes())
    actual_edges = _edge_set(graph)
    expected_nodes, expected_edges = _load_expected_example()

    node_intersection = actual_nodes & expected_nodes
    edge_intersection = actual_edges & expected_edges

    node_precision = len(node_intersection) / len(actual_nodes) if actual_nodes else 0.0
    node_recall = len(node_intersection) / len(expected_nodes) if expected_nodes else 0.0
    edge_precision = len(edge_intersection) / len(actual_edges) if actual_edges else 0.0
    edge_recall = len(edge_intersection) / len(expected_edges) if expected_edges else 0.0

    return {
        "node_precision": round(node_precision, 4),
        "node_recall": round(node_recall, 4),
        "edge_precision": round(edge_precision, 4),
        "edge_recall": round(edge_recall, 4),
        "nodes_expected": len(expected_nodes),
        "nodes_actual": len(actual_nodes),
        "edges_expected": len(expected_edges),
        "edges_actual": len(actual_edges),
    }


def benchmark_query_utility():
    example_repo = REPO_ROOT / "example_repo"
    parsed_repo = _build_parsed_repo(example_repo)
    payload = json.dumps({"parsed_repo": parsed_repo})

    queries = [
        {
            "query": "login",
            "expected": {
                "auth.login_user",
                "auth.audit_login",
            },
        },
        {
            "query": "profile",
            "expected": {
                "models.ProfileService.load_profile",
                "models.ProfileService.save_profile",
            },
        },
        {
            "query": "email",
            "expected": {
                "emailer.send_welcome_email",
                "emailer.Mailer.deliver_message",
            },
        },
    ]

    results = []
    for item in queries:
        symbol_map = symbol_extractor(item["query"], payload)
        nodes = _flatten_symbol_map(symbol_map)
        expected = set(item["expected"])
        hit = len(nodes & expected)
        recall = hit / len(expected) if expected else 0.0
        results.append(
            {
                "query": item["query"],
                "expected_count": len(expected),
                "returned_count": len(nodes),
                "hit_count": hit,
                "recall": round(recall, 4),
            }
        )
    return results


def benchmark_context_reduction():
    example_repo = REPO_ROOT / "example_repo"
    parsed_repo = _build_parsed_repo(example_repo)
    payload = json.dumps({"parsed_repo": parsed_repo})

    all_files = [p for p in example_repo.rglob("*.py") if p.is_file()]
    total_loc = _count_loc(all_files)

    queries = ["login", "profile", "email"]
    results = []
    for query in queries:
        symbol_map = symbol_extractor(query, payload)
        file_paths = [example_repo / name for name in symbol_map.keys()]
        selected_loc = _count_loc(file_paths)
        ratio = (selected_loc / total_loc) if total_loc else 0.0
        results.append(
            {
                "query": query,
                "total_loc": total_loc,
                "selected_loc": selected_loc,
                "selected_ratio": round(ratio, 4),
                "reduction": round(1 - ratio, 4),
            }
        )
    return results


def benchmark_end_to_end():
    example_repo = REPO_ROOT / "example_repo"
    parsed_repo = _build_parsed_repo(example_repo)
    payload = json.dumps({"parsed_repo": parsed_repo})

    all_files = [p for p in example_repo.rglob("*.py") if p.is_file()]
    total_loc = _count_loc(all_files)

    tasks = [
        {
            "task": "trace_login_flow",
            "query": "login",
            "expected": {
                "auth.login_user",
                "auth.audit_login",
                "auth.store_audit_entry",
            },
        },
        {
            "task": "profile_save_path",
            "query": "profile",
            "expected": {
                "models.ProfileService.save_profile",
                "models.persist_profile",
            },
        },
        {
            "task": "welcome_email",
            "query": "email",
            "expected": {
                "emailer.send_welcome_email",
                "emailer.Mailer.deliver_message",
                "emailer.compose_body",
            },
        },
    ]

    results = []
    for item in tasks:
        symbol_map = symbol_extractor(item["query"], payload)
        nodes = _flatten_symbol_map(symbol_map)
        expected = set(item["expected"])
        hit = len(nodes & expected)
        recall = hit / len(expected) if expected else 0.0

        file_paths = [example_repo / name for name in symbol_map.keys()]
        selected_loc = _count_loc(file_paths)
        selected_ratio = (selected_loc / total_loc) if total_loc else 0.0

        total_words = total_loc * WORDS_PER_LOC
        selected_words = selected_loc * WORDS_PER_LOC
        full_time_min = total_words / READ_WPM if READ_WPM else 0.0
        selected_time_min = selected_words / READ_WPM if READ_WPM else 0.0

        results.append(
            {
                "task": item["task"],
                "query": item["query"],
                "expected_count": len(expected),
                "hit_count": hit,
                "recall": round(recall, 4),
                "total_loc": total_loc,
                "selected_loc": selected_loc,
                "selected_ratio": round(selected_ratio, 4),
                "estimated_full_read_min": round(full_time_min, 2),
                "estimated_selected_read_min": round(selected_time_min, 2),
            }
        )
    return {
        "assumptions": {
            "read_wpm": READ_WPM,
            "words_per_loc": WORDS_PER_LOC,
        },
        "results": results,
    }


def _load_real_repos():
    config_path = REPO_ROOT / "benchmarks" / "real_repos.json"
    if not config_path.exists():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    repos = data.get("repos", [])
    return [r for r in repos if r.get("path")]


def _agent_comparison_for_repo(repo_path: Path, queries):
    basename_index = build_basename_index(repo_path)
    all_files = [p for p in repo_path.rglob("*.py") if p.is_file()]
    total_loc = _count_loc(all_files)

    results = []
    for item in queries:
        query = item["query"]
        depth = item.get("depth", 2)

        start = time.perf_counter()
        arch = run_cli_json(REPO_ROOT, ["architecture", str(repo_path), query])
        arch_time = time.perf_counter() - start

        start = time.perf_counter()
        conn = run_cli_json(REPO_ROOT, ["connections", str(repo_path), query, str(depth), "--compact"])
        conn_time = time.perf_counter() - start

        baseline_files = baseline_retrieval(query, all_files)
        baseline_text = _collect_text_from_files(baseline_files)
        baseline_tokens = _estimate_tokens(baseline_text)
        baseline_words = _count_loc(baseline_files) * WORDS_PER_LOC
        baseline_read_min = baseline_words / READ_WPM if READ_WPM else 0.0

        arch_files = resolve_selected_files(repo_path, arch.keys(), basename_index)
        conn_files = files_from_connections(conn, basename_index)
        selected_files = list(set(arch_files + conn_files))
        selected_loc = _count_loc(selected_files)
        selected_text = _collect_text_from_files(selected_files)
        selected_tokens = _estimate_tokens(selected_text)
        selected_words = selected_loc * WORDS_PER_LOC
        selected_read_min = selected_words / READ_WPM if READ_WPM else 0.0

        results.append(
            {
                "query": query,
                "depth": depth,
                "baseline": {
                    "total_loc": total_loc,
                    "tokens_estimate": baseline_tokens,
                    "estimated_read_min": round(baseline_read_min, 2),
                    "files_used": len(baseline_files),
                },
                "repograph": {
                    "selected_loc": selected_loc,
                    "tokens_estimate": selected_tokens,
                    "estimated_read_min": round(selected_read_min, 2),
                    "architecture_time_s": round(arch_time, 4),
                    "connections_time_s": round(conn_time, 4),
                    "matched_nodes": len(conn.get("n", [])),
                    "edges": len(conn.get("e", [])),
                    "files_used": len(selected_files),
                },
                "savings": {
                    "loc_reduction": round(1 - (selected_loc / total_loc), 4) if total_loc else 0.0,
                    "token_reduction": round(1 - (selected_tokens / baseline_tokens), 4) if baseline_tokens else 0.0,
                    "read_time_reduction": round(1 - (selected_read_min / baseline_read_min), 4) if baseline_read_min else 0.0,
                },
            }
        )

    return {
        "repo": str(repo_path),
        "results": results,
    }


def benchmark_agent_comparison():
    repos = _load_real_repos()
    if not repos:
        repos = [
            {
                "name": "example_repo",
                "path": str(REPO_ROOT / "example_repo"),
                "queries": [
                    {"query": "login", "depth": 2},
                    {"query": "profile", "depth": 2},
                    {"query": "email", "depth": 2},
                ],
            }
        ]

    output = []
    skipped = []
    for repo in repos:
        repo_path = Path(repo["path"]).expanduser()
        if not repo_path.exists():
            skipped.append(
                {
                    "name": repo.get("name") or repo_path.name,
                    "path": str(repo_path),
                    "reason": "path_not_found",
                }
            )
            continue
        queries = repo.get("queries") or [
            {"query": "login", "depth": 2},
            {"query": "profile", "depth": 2},
            {"query": "email", "depth": 2},
        ]
        output.append(
            {
                "name": repo.get("name") or repo_path.name,
                **_agent_comparison_for_repo(repo_path, queries),
            }
        )

    return {
        "assumptions": {
            "read_wpm": READ_WPM,
            "words_per_loc": WORDS_PER_LOC,
            "chars_per_token": CHARS_PER_TOKEN,
        },
        "repos": output,
        "skipped": skipped,
    }


def _generate_synth_repo(root: Path, files: int, funcs: int, fanout: int):
    if root.exists():
        for item in root.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(root.glob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
    root.mkdir(parents=True, exist_ok=True)

    for i in range(files):
        next_idx = (i + 1) % files
        file_name = f"file_{i}.py"
        next_module = f"file_{next_idx}"
        lines = [f"import {next_module}", ""]
        for j in range(funcs):
            lines.append(f"def f_{i}_{j}():")
            calls = []
            for k in range(1, fanout + 1):
                target = (j + k) % funcs
                calls.append(f"    f_{i}_{target}()")
            if j == funcs - 1:
                calls.append(f"    {next_module}.f_{next_idx}_0()")
            lines.extend(calls or ["    pass"])
            lines.append("")
        (root / file_name).write_text("\n".join(lines), encoding="utf-8")


def benchmark_performance_scaling():
    tmp_root = REPO_ROOT / "benchmarks" / "tmp"
    sizes = [
        {"files": 5, "funcs": 20, "fanout": 2},
        {"files": 10, "funcs": 30, "fanout": 2},
        {"files": 20, "funcs": 40, "fanout": 3},
    ]

    results = []
    for config in sizes:
        name = f"synth_f{config['files']}_fn{config['funcs']}_fo{config['fanout']}"
        repo_path = tmp_root / name
        _generate_synth_repo(repo_path, **config)

        start = time.perf_counter()
        parsed_repo = _build_parsed_repo(repo_path)
        graph = build_graph(parsed_repo)
        elapsed = time.perf_counter() - start

        results.append(
            {
                "repo": name,
                "files": config["files"],
                "funcs_per_file": config["funcs"],
                "fanout": config["fanout"],
                "nodes": len(graph.nodes()),
                "edges": len(graph.edges()),
                "time_s": round(elapsed, 4),
            }
        )
    return results


def main():
    summary = {
        "agent_comparison": benchmark_agent_comparison(),
        "diagnostics": {
            "example_repo_correctness": benchmark_example_repo_correctness(),
            "query_utility": benchmark_query_utility(),
            "context_reduction": benchmark_context_reduction(),
            "end_to_end": benchmark_end_to_end(),
            "performance_scaling": benchmark_performance_scaling(),
        },
    }

    results_path = REPO_ROOT / "benchmarks" / "results" / "benchmark_results.json"
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("Benchmark summary")
    print(json.dumps(summary, indent=2))
    print(f"\nSaved to: {results_path}")


if __name__ == "__main__":
    main()
