"""
Co-change graph analyzer.

Mines git history to find files that are BEHAVIORALLY coupled —
i.e., they are edited together in commits, even when they have
no direct structural connection (no calls, no imports).

This captures hidden invariants, parallel implementations, and
configuration/test coupling that static call-graph analysis misses.

Key function: build_cochange_graph(repo_path) -> CoChangeGraph
"""

import subprocess
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import math


class CoChangeGraph:
    """
    Holds the co-change frequency matrix and exposes lookup methods.

    cochange_pairs: dict mapping (file_a, file_b) → CoChangePair
    file_index:     dict mapping file_basename → list of full relative paths seen in git
    """

    def __init__(self, pairs: dict, file_index: dict, total_commits: int):
        self.pairs = pairs          # (a, b) → CoChangePair
        self.file_index = file_index
        self.total_commits = total_commits

    def partners(self, filename: str, top_k: int = 5) -> list:
        """
        Return top-k co-change partners for `filename` (basename or relative path).
        Each entry: {"file": str, "cochange_rate": float, "count": int, "score": float}
        Sorted by score descending.
        """
        stem = Path(filename).name  # normalize to basename

        results = []
        for (a, b), pair in self.pairs.items():
            partner = None
            if Path(a).name == stem:
                partner = b
            elif Path(b).name == stem:
                partner = a
            if partner is None:
                continue
            results.append({
                "file": partner,
                "cochange_rate": round(pair.rate, 3),
                "count": pair.count,
                "score": round(pair.score, 4),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def all_partners_for_files(self, filenames: list, top_k: int = 5) -> list:
        """
        Return union of top-k partners for a list of files.
        Aggregates scores across all seed files, deduplicates, returns ranked list.
        """
        seed_set = {Path(f).name for f in filenames}
        agg = defaultdict(float)

        for fname in filenames:
            for p in self.partners(fname, top_k=20):
                partner_name = Path(p["file"]).name
                if partner_name not in seed_set:
                    agg[p["file"]] = max(agg[p["file"]], p["score"])

        ranked = sorted(agg.items(), key=lambda x: x[1], reverse=True)
        return [{"file": f, "score": round(s, 4)} for f, s in ranked[:top_k]]


class CoChangePair:
    __slots__ = ("count", "rate", "score")

    def __init__(self, count: int, rate: float, score: float):
        self.count = count
        self.rate = rate
        self.score = score


def build_cochange_graph(
    repo_path: str,
    max_commits: int = 5000,
    min_count: int = 1,
    decay_halflife_days: float = 0.0,
    py_only: bool = True,
) -> CoChangeGraph:
    """
    Parse git log and build the co-change graph.

    Parameters
    ----------
    repo_path        : absolute path to a git repository root
    max_commits      : how many recent commits to analyse (more = richer graph, slower)
    min_count        : minimum number of co-occurrences to include a pair
    decay_halflife_days : recent co-changes count more. Half-life in days.
                          Set to 0 to disable decay.
    py_only          : if True, only consider .py files

    Returns
    -------
    CoChangeGraph
    """
    repo = Path(repo_path)

    # --- 1. Extract commits: list of (timestamp, [files]) ---------------
    raw = _git_log(repo, max_commits)
    commits = _parse_log(raw, py_only=py_only)

    if not commits:
        return CoChangeGraph({}, {}, 0)

    now_ts = datetime.now(timezone.utc).timestamp()
    decay_lambda = math.log(2) / (decay_halflife_days * 86400) if decay_halflife_days > 0 else 0

    # --- 2. Count co-occurrences per file pair --------------------------
    # pair_count[a][b] = raw number of commits where both appear
    pair_count: dict[tuple, float] = defaultdict(float)
    file_commit_count: dict[str, int] = defaultdict(int)  # how many commits touched each file

    for ts, files in commits:
        if len(files) < 2:
            continue
        # temporal weight: recent commits matter more
        age_seconds = now_ts - ts
        weight = math.exp(-decay_lambda * age_seconds) if decay_lambda > 0 else 1.0

        for fname in files:
            file_commit_count[fname] += 1

        # generate all pairs in this commit (order-independent)
        files_sorted = sorted(set(files))
        for i in range(len(files_sorted)):
            for j in range(i + 1, len(files_sorted)):
                a, b = files_sorted[i], files_sorted[j]
                pair_count[(a, b)] += weight

    # --- 3. Build CoChangePair objects with Jaccard-like rate -----------
    # rate = count(a∩b) / count(a∪b)  [Jaccard co-change coefficient]
    pairs = {}
    file_index: dict[str, list] = defaultdict(list)

    for (a, b), weighted_count in pair_count.items():
        raw_count = int(round(weighted_count))
        if raw_count < min_count:
            continue

        # Jaccard: how often do they change together vs. independently
        union = file_commit_count[a] + file_commit_count[b] - raw_count
        rate = raw_count / max(1, union)

        # final score: combines frequency and coupling strength
        score = rate * math.log1p(raw_count)

        pairs[(a, b)] = CoChangePair(count=raw_count, rate=rate, score=score)

        for fname in (a, b):
            bname = Path(fname).name
            if fname not in file_index[bname]:
                file_index[bname].append(fname)

    return CoChangeGraph(pairs, dict(file_index), len(commits))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def build_cochange_graph_from_commits(
    commits: list,
    min_count: int = 1,
    decay_halflife_days: float = 0.0,
) -> "CoChangeGraph":
    """
    Build a CoChangeGraph from a pre-parsed list of (timestamp, [files]) tuples.
    Useful for train/test splitting without re-running git.
    """
    if not commits:
        return CoChangeGraph({}, {}, 0)

    now_ts = commits[0][0]  # most recent commit as reference
    decay_lambda = math.log(2) / (decay_halflife_days * 86400) if decay_halflife_days > 0 else 0

    pair_count: dict[tuple, float] = defaultdict(float)
    file_commit_count: dict[str, int] = defaultdict(int)

    for ts, files in commits:
        if len(files) < 2:
            continue
        age_seconds = max(0, now_ts - ts)
        weight = math.exp(-decay_lambda * age_seconds) if decay_lambda > 0 else 1.0

        for fname in files:
            file_commit_count[fname] += 1

        files_sorted = sorted(set(files))
        for i in range(len(files_sorted)):
            for j in range(i + 1, len(files_sorted)):
                a, b = files_sorted[i], files_sorted[j]
                pair_count[(a, b)] += weight

    pairs = {}
    file_index: dict[str, list] = defaultdict(list)

    for (a, b), weighted_count in pair_count.items():
        raw_count = int(round(weighted_count))
        if raw_count < min_count:
            continue

        union = file_commit_count[a] + file_commit_count[b] - raw_count
        rate = raw_count / max(1, union)
        score = rate * math.log1p(raw_count)

        pairs[(a, b)] = CoChangePair(count=raw_count, rate=rate, score=score)

        for fname in (a, b):
            bname = Path(fname).name
            if fname not in file_index[bname]:
                file_index[bname].append(fname)

    return CoChangeGraph(pairs, dict(file_index), len(commits))


def _git_log(repo: Path, max_commits: int) -> str:
    """Run git log and return raw output."""
    try:
        result = subprocess.run(
            [
                "git", "log",
                "--no-merges",
                f"-n{max_commits}",
                "--name-only",
                "--format=COMMIT %ct",   # unix timestamp per commit
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _parse_log(raw: str, py_only: bool) -> list:
    """
    Parse git log output into list of (unix_timestamp, [files]).
    """
    commits = []
    current_ts = None
    current_files = []

    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("COMMIT "):
            if current_ts is not None and current_files:
                commits.append((current_ts, current_files))
            try:
                current_ts = float(line.split()[1])
            except (IndexError, ValueError):
                current_ts = 0.0
            current_files = []
        elif line:
            if py_only and not line.endswith(".py"):
                continue
            # normalize: use only the basename to avoid full-path fragility
            current_files.append(line)

    if current_ts is not None and current_files:
        commits.append((current_ts, current_files))

    return commits
