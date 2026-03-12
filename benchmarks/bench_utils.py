import json
import re
import subprocess
import sys
from pathlib import Path


def run_cli_json(repo_root: Path, args):
    cmd = [sys.executable, str(repo_root / "cli" / "repograph_cli.py"), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "CLI error")
    return json.loads(proc.stdout)


def build_basename_index(repo_path: Path, extensions=(".py",)):
    index = {}
    for ext in extensions:
        for file_path in repo_path.rglob(f"*{ext}"):
            index.setdefault(file_path.name, []).append(file_path)
    return index


def resolve_selected_files(repo_path: Path, file_names, basename_index):
    resolved = []
    for name in file_names:
        candidate = repo_path / name
        if candidate.exists():
            resolved.append(candidate)
            continue
        resolved.extend(basename_index.get(name, []))
    return resolved


def read_file(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def build_context(files):
    parts = []
    for path in files:
        rel = path.as_posix()
        parts.append(f"\n# File: {rel}\n")
        parts.append(read_file(path))
        parts.append("\n")
    return "".join(parts)


def keyword_score(query, text):
    tokens = re.findall(r"\w+", query.lower())
    text = text.lower()
    return sum(text.count(t) for t in tokens)


def baseline_retrieval(query, repo_files, k=8):
    scored = []
    for path in repo_files:
        text = read_file(path)
        score = keyword_score(query, text)
        scored.append((score, path))
    scored.sort(reverse=True)
    return [p for _, p in scored[:k]]


def files_from_connections(conn, basename_index):
    files = set()
    nodes = (
        conn.get("rn")
        or conn.get("ranked_nodes")
        or conn.get("n", [])
    )
    for node in nodes:
        if "." in node:
            module = node.split(".")[0] + ".py"
            files.add(module)
    resolved = []
    for f in files:
        resolved.extend(basename_index.get(f, []))
    return resolved
