import sys
sys.path.insert(0, ".")
from cochange.cochange_analyzer import build_cochange_graph, _git_log, _parse_log
from pathlib import Path

repo = "C:/Users/ssamu/OneDrive/Desktop/github-biran2/brian2"

raw = _git_log(Path(repo), 5000)
commits = _parse_log(raw, py_only=True)
print(f"Total non-merge commits: {len(commits)}")

multi = [c for c in commits if len(c[1]) >= 2]
print(f"Multi-file commits: {len(multi)}")
print(f"Sample commit files: {multi[0][1][:4] if multi else 'none'}")

# No decay, min_count=1
cg_nodecay = build_cochange_graph(repo, max_commits=5000, min_count=1, decay_halflife_days=0)
print(f"\nWith no decay, min=1: {len(cg_nodecay.pairs)} pairs")

# With decay=365, min=1
cg_decay = build_cochange_graph(repo, max_commits=5000, min_count=1, decay_halflife_days=365)
print(f"With decay=365, min=1: {len(cg_decay.pairs)} pairs")

# With decay=365, min=2 (original)
cg_orig = build_cochange_graph(repo, max_commits=1000, min_count=2, decay_halflife_days=365)
print(f"Original (max=1000, decay=365, min=2): {len(cg_orig.pairs)} pairs")

print("\nTop partners of neurongroup.py (no decay):")
for p in cg_nodecay.partners("neurongroup.py", top_k=5):
    print(f"  {p}")

print("\nTop partners of network.py (no decay):")
for p in cg_nodecay.partners("network.py", top_k=5):
    print(f"  {p}")

print("\nTop partners of clocks.py (no decay):")
for p in cg_nodecay.partners("clocks.py", top_k=5):
    print(f"  {p}")
