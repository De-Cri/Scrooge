"""
Real-task benchmark: Aider repo map vs Scrooge (structural + co-change).

THREE LEVELS OF MEASUREMENT
-----------------------------

Level 1 — Context quality (no API needed, deterministic):
  For each real git commit (trigger file + required co-changed files):
  - Generate Aider repo map context
  - Generate Scrooge context (structural + cochange_alerts)
  - Count: does each context surface the co-changed files?
  - This tells us: if Claude saw this context, could it know what to edit?

Level 2 — Context token budget:
  How many tokens does each context consume? Smaller = better for agent cost.

Level 3 — Side-by-side human-readable output:
  For 3 tasks, print what each tool gives the agent.
  Anyone can read and judge which context would produce a more complete edit.

TASKS
-----
Real commits from brian2 with clear multi-file change patterns.
Each task: commit message (the agent's goal) + files actually changed.
"""

import json
import sys
import io
import time
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cochange.cochange_analyzer import build_cochange_graph_from_commits, _git_log, _parse_log
from scanner.scanner import scan_repo
from parser.ast_parser import parse_file
from graph_builder.call_graph import build_graph
from graph_builder.symbols_connections import generate_complete_connections
from indexer.symbol_extractor import symbol_extractor
import math, re

AIDER_PYTHON  = "C:/Users/ssamu/OneDrive/Desktop/aider_env/Scripts/python.exe"
AIDER_HELPER  = str(Path(__file__).parent / "_aider_repomap_helper.py")
BRIAN2_REPO   = "C:/Users/ssamu/OneDrive/Desktop/github-biran2/brian2"

_EXCLUDE = re.compile(
    r"([\\/]tests?[\\/]|[\\/]examples?[\\/]|[\\/]dev[\\/]|test_[^/\\]*\.py$"
    r"|_test\.py$|conftest\.py$|setup\.py$|__init__\.py$)"
)


# ──────────────────────────────────────────────────────────────────────────────
# Task extraction from real git commits
# ──────────────────────────────────────────────────────────────────────────────

def extract_tasks(repo_path: str, n: int = 8) -> list:
    """
    Extract n real coding tasks from git history.
    Each task: commit message + list of source files changed.
    Filter: commits with 2-4 source files and a meaningful commit message.
    """
    import subprocess
    result = subprocess.run(
        ["git", "log", "--no-merges", "-n300",
         "--format=COMMIT %H %s",
         "--name-only", "--diff-filter=M"],
        cwd=repo_path, capture_output=True, text=True, timeout=30
    )

    tasks = []
    current_hash = None
    current_msg = None
    current_files = []

    for line in result.stdout.splitlines():
        if line.startswith("COMMIT "):
            if current_hash and current_files:
                src = [f for f in current_files
                       if f.endswith(".py") and not _EXCLUDE.search(f)]
                if 2 <= len(src) <= 4 and len(current_msg) > 20:
                    tasks.append({
                        "hash": current_hash,
                        "message": current_msg,
                        "files": src,
                        "trigger": src[0],
                        "targets": src[1:],
                    })
            parts = line.split(" ", 2)
            current_hash = parts[1] if len(parts) > 1 else ""
            current_msg = parts[2] if len(parts) > 2 else ""
            current_files = []
        elif line.strip():
            current_files.append(line.strip())

    return tasks[:n]


# ──────────────────────────────────────────────────────────────────────────────
# Aider RepoMap context generator
# ──────────────────────────────────────────────────────────────────────────────

def get_aider_repomap(repo_path: str, trigger_file: str = "") -> str:
    """
    Generate Aider repo map via subprocess (aider venv Python 3.11).
    This is exactly what Aider gives Claude as context before a task.
    """
    import subprocess
    try:
        result = subprocess.run(
            [AIDER_PYTHON, AIDER_HELPER, repo_path, trigger_file or "", "1500"],
            capture_output=True, text=True, timeout=60
        )
        out = result.stdout.strip()
        # Find the JSON line (last non-empty line)
        for line in reversed(out.splitlines()):
            if line.startswith("{"):
                data = json.loads(line)
                if data.get("error"):
                    return f"(aider error: {data['error'][:80]})"
                return data.get("repomap", "")
        return "(no repomap output)"
    except Exception as e:
        return f"(subprocess error: {e})"


# ──────────────────────────────────────────────────────────────────────────────
# Scrooge context generator
# ──────────────────────────────────────────────────────────────────────────────

def get_scrooge_context(repo_path: str, query: str, graph, parsed_repo: dict,
                        cg, symbol_map_cache: dict = None) -> dict:
    """
    Generate full Scrooge context: structural candidates + co-change alerts.
    Returns dict with candidates list and cochange_alerts.
    """
    parsed_payload = json.dumps({"parsed_repo": parsed_repo})
    symbol_map = symbol_extractor(query, parsed_payload)

    def sym_to_nodes(sm):
        nodes = []
        for fname, fdata in sm.items():
            stem = Path(fname).stem
            for fn in fdata.get("functions", {}):
                nodes.append(f"{stem}.{fn}")
            for cls, cd in fdata.get("classes", {}).items():
                for mn in cd.get("methods", {}):
                    nodes.append(f"{stem}.{cls}.{mn}")
        return nodes

    matched_nodes = sorted(set(sym_to_nodes(symbol_map)))
    if not matched_nodes:
        return {"candidates": [], "cochange_alerts": [], "query": query}

    symbol_list = [{"name": n, "type": "function"} for n in matched_nodes]
    try:
        connections_list, ranked_nodes, node_scores = generate_complete_connections(
            symbol_list, graph, depth=2, rank_keep_pct=1.0, return_scores=True,
        )
    except Exception:
        return {"candidates": [], "cochange_alerts": [], "query": query}

    # Build candidates
    token_cov = {f: symbol_map.get(Path(f).stem + ".py", {}).get("_token_coverage", 0.0)
                 for f in symbol_map}

    file_scores = {}
    for fname in symbol_map:
        prefix = Path(fname).stem + "."
        gs = max((node_scores.get(n, 0) for n in node_scores if n.startswith(prefix)), default=0)
        cov = symbol_map[fname].get("_token_coverage", 0.0)
        file_scores[fname] = gs * 0.7 + cov * 0.3

    top_score = max(file_scores.values(), default=1) or 1
    candidates = [
        {"file": f, "relevance": round(file_scores[f] / top_score * 100)}
        for f in sorted(file_scores, key=lambda x: file_scores[x], reverse=True)[:5]
    ]

    # Co-change alerts for candidate files
    candidate_names = [Path(c["file"]).name for c in candidates]
    cochange_alerts = cg.all_partners_for_files(candidate_names, top_k=5)

    return {
        "query": query,
        "candidates": candidates,
        "cochange_alerts": cochange_alerts,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def context_contains(context_text_or_dict, target_files: list) -> dict:
    """Check which target files appear in the context."""
    if isinstance(context_text_or_dict, str):
        text = context_text_or_dict.lower()
    else:
        text = json.dumps(context_text_or_dict).lower()

    results = {}
    for f in target_files:
        fname = Path(f).name
        stem = Path(f).stem
        results[fname] = (fname.lower() in text or stem.lower() in text)
    return results


def count_tokens(text: str) -> int:
    return max(1, len(str(text)) // 4)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def run():
    print("Building structural graph and co-change graph for brian2...")
    t0 = time.perf_counter()

    files = scan_repo(BRIAN2_REPO)
    parsed_repo = {"files": {}}
    for f in files:
        if f.suffix == ".py" and not _EXCLUDE.search(str(f).replace("\\", "/")):
            pf = parse_file(f)
            parsed_repo["files"].update(pf.get("files", {}))
    graph = build_graph(parsed_repo)

    raw = _git_log(Path(BRIAN2_REPO), 5080)
    all_commits = _parse_log(raw, py_only=True)
    cg = build_cochange_graph_from_commits(all_commits[80:], min_count=1)

    print(f"  Graph: {graph.number_of_nodes()} nodes | Co-change: {len(cg.pairs)} pairs ({time.perf_counter()-t0:.1f}s)")

    # Extract tasks
    tasks = extract_tasks(BRIAN2_REPO, n=8)
    print(f"  Tasks extracted: {len(tasks)}\n")

    if not tasks:
        print("No tasks found.")
        return

    # Results
    level1 = []  # context quality (file hit rate)
    level2 = []  # token counts

    for i, task in enumerate(tasks, 1):
        trigger = task["trigger"]
        targets = task["targets"]
        msg     = task["message"]
        trigger_name = Path(trigger).name

        # Extract keyword query from commit message (simple: take first 4 meaningful words)
        stop = {"the","a","an","in","of","to","and","or","for","fix","add","update",
                "change","use","with","from","this","that","when","if","is","are","was"}
        query_words = [w.lower() for w in re.split(r'\W+', msg) if w.lower() not in stop and len(w)>2]
        query = " ".join(query_words[:4])

        # ---- Aider repo map ----
        t0 = time.perf_counter()
        aider_context = get_aider_repomap(BRIAN2_REPO, trigger)
        aider_time = time.perf_counter() - t0

        # ---- Scrooge ----
        t0 = time.perf_counter()
        scrooge_ctx = get_scrooge_context(BRIAN2_REPO, query, graph, parsed_repo, cg)
        scrooge_time = time.perf_counter() - t0

        # ---- Evaluate ----
        aider_hits  = context_contains(aider_context, targets)
        scrooge_hits = context_contains(scrooge_ctx, targets)

        aider_recall  = sum(aider_hits.values()) / max(1, len(targets))
        scrooge_recall = sum(scrooge_hits.values()) / max(1, len(targets))

        aider_tokens  = count_tokens(aider_context)
        scrooge_tokens = count_tokens(json.dumps(scrooge_ctx))

        level1.append({
            "task": i,
            "msg": msg[:60],
            "trigger": trigger_name,
            "targets": [Path(t).name for t in targets],
            "aider_recall": round(aider_recall, 2),
            "scrooge_recall": round(scrooge_recall, 2),
            "aider_tokens": aider_tokens,
            "scrooge_tokens": scrooge_tokens,
        })
        level2.append({
            "aider_time": round(aider_time, 2),
            "scrooge_time": round(scrooge_time, 2),
        })

        winner = "SCROOGE" if scrooge_recall > aider_recall else ("AIDER" if aider_recall > scrooge_recall else "TIE")
        print(f"Task {i}: {msg[:55]}")
        print(f"  Trigger: {trigger_name}  |  Targets: {[Path(t).name for t in targets]}")
        print(f"  Aider recall:   {aider_recall:.2f}  ({aider_tokens} tokens)")
        print(f"  Scrooge recall: {scrooge_recall:.2f}  ({scrooge_tokens} tokens)")
        print(f"  Winner: {winner}\n")

    # Summary
    avg_aider   = sum(r["aider_recall"] for r in level1) / len(level1)
    avg_scrooge = sum(r["scrooge_recall"] for r in level1) / len(level1)
    avg_at      = sum(r["aider_tokens"] for r in level1) / len(level1)
    avg_st      = sum(r["scrooge_tokens"] for r in level1) / len(level1)

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'Metric':<35} {'Aider':>8} {'Scrooge':>10}")
    print("-" * 55)
    print(f"{'Avg context recall (target files hit)':<35} {avg_aider:>8.3f} {avg_scrooge:>10.3f}")
    print(f"{'Avg tokens per context':<35} {avg_at:>8.0f} {avg_st:>10.0f}")

    wins_s = sum(1 for r in level1 if r["scrooge_recall"] > r["aider_recall"])
    wins_a = sum(1 for r in level1 if r["aider_recall"] > r["scrooge_recall"])
    ties   = len(level1) - wins_s - wins_a
    print(f"\nScrooge wins: {wins_s}  |  Aider wins: {wins_a}  |  Ties: {ties}")

    if avg_aider > 0:
        rel = round((avg_scrooge - avg_aider) / avg_aider * 100)
        print(f"Relative improvement: {rel:+d}%")

    # Level 3: side-by-side for first 2 tasks
    print("\n" + "="*60)
    print("SIDE-BY-SIDE CONTEXT COMPARISON (first 2 tasks)")
    print("="*60)

    out_lines = []
    for i, task in enumerate(tasks[:3], 1):
        trigger = task["trigger"]
        targets = task["targets"]
        stop = {"the","a","an","in","of","to","and","or","for","fix","add","update",
                "change","use","with","from","this","that","when","if","is","are","was"}
        query_words = [w.lower() for w in re.split(r'\W+', task["message"])
                       if w.lower() not in stop and len(w) > 2]
        query = " ".join(query_words[:4])

        aider_ctx   = get_aider_repomap(BRIAN2_REPO, trigger)
        scrooge_ctx = get_scrooge_context(BRIAN2_REPO, query, graph, parsed_repo, cg)

        # Sanitize unicode for Windows terminal
        aider_safe = aider_ctx.encode("ascii", "replace").decode("ascii")

        out_lines.append(f"\nTask {i}: {task['message'][:70]}")
        out_lines.append(f"Trigger: {Path(trigger).name}  Targets: {[Path(t).name for t in targets]}")
        out_lines.append(f"\n--- AIDER CONTEXT ({count_tokens(aider_ctx)} tokens) ---")
        for line in aider_safe.splitlines()[:35]:
            out_lines.append(line)
        if len(aider_safe.splitlines()) > 35:
            out_lines.append(f"... ({len(aider_safe.splitlines())-35} more lines)")
        out_lines.append(f"\n--- SCROOGE CONTEXT ({count_tokens(json.dumps(scrooge_ctx))} tokens) ---")
        out_lines.append(json.dumps(scrooge_ctx, indent=2))
        out_lines.append("\n--- FILE COVERAGE ---")
        for target in targets:
            tn = Path(target).name
            in_aider   = tn.lower() in aider_ctx.lower() or Path(target).stem.lower() in aider_ctx.lower()
            in_scrooge = tn.lower() in json.dumps(scrooge_ctx).lower()
            out_lines.append(f"  {tn}: Aider={'HIT' if in_aider else 'MISS'} | Scrooge={'HIT' if in_scrooge else 'MISS'}")

    for line in out_lines:
        print(line)

    # Save
    out = Path(__file__).parent / "real_task_results.json"
    out.write_text(json.dumps({"tasks": level1, "timings": level2}, indent=2), encoding="utf-8")
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    run()
