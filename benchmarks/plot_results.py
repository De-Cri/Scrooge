"""
Generate benchmark comparison charts from gemini_agent_results.json.
Saves benchmark_chart.png in the same directory.
"""

import json
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "results", "gemini_agent_results.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "results", "benchmark_chart.png")

# ── Load data ────────────────────────────────────────────────────────────────

with open(RESULTS_FILE) as f:
    data = json.load(f)

classic = data["results"][0]["queries"][0]["agents"][0]["final"]
repograph = data["results with REPOGRAH"][0]["queries"][0]["agents"][0]["final"]

files_classic   = classic["files_used"]
files_repograph = repograph["files_used"]
tokens_classic   = classic["token_count_estimate"]
tokens_repograph = repograph["token_count_estimate"]

# ── Palette ──────────────────────────────────────────────────────────────────

CLASSIC_COLOR   = "#e07b54"   # warm orange
REPOGRAPH_COLOR = "#4a90d9"   # clear blue
BG_COLOR        = "#0f1117"
PANEL_COLOR     = "#1a1d27"
TEXT_COLOR       = "#e8eaf0"
GRID_COLOR       = "#2a2d3a"

# ── Layout ───────────────────────────────────────────────────────────────────

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5.5))
fig.patch.set_facecolor(BG_COLOR)

labels   = ["Classic\nagent", "Scrooge\nagent"]
x        = np.array([0, 1])
bar_w    = 0.45

# ── Helper: style axes ───────────────────────────────────────────────────────

def style_ax(ax, title, ylabel):
    ax.set_facecolor(PANEL_COLOR)
    ax.set_title(title, color=TEXT_COLOR, fontsize=13, fontweight="bold", pad=12)
    ax.set_ylabel(ylabel, color=TEXT_COLOR, fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, color=TEXT_COLOR, fontsize=11)
    ax.tick_params(colors=TEXT_COLOR, which="both")
    ax.yaxis.set_tick_params(labelcolor=TEXT_COLOR)
    ax.grid(axis="y", color=GRID_COLOR, linewidth=0.8, linestyle="--")
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COLOR)

# ── Chart 1 — Files opened ───────────────────────────────────────────────────

bars1 = ax1.bar(x, [files_classic, files_repograph], width=bar_w,
                color=[CLASSIC_COLOR, REPOGRAPH_COLOR],
                edgecolor="none", zorder=3)
style_ax(ax1, "Files Opened", "files")
ax1.set_ylim(0, files_classic * 1.45)

for bar, val in zip(bars1, [files_classic, files_repograph]):
    ax1.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 0.12,
             str(val), ha="center", va="bottom",
             color=TEXT_COLOR, fontsize=13, fontweight="bold")

# reduction label
ratio_files = files_classic / files_repograph
ax1.text(0.5, 0.88, f"{ratio_files:.0f}× fewer files",
         transform=ax1.transAxes, ha="center",
         color="#a8d8a8", fontsize=11, fontweight="bold")

# ── Chart 2 — Prompt tokens ──────────────────────────────────────────────────

bars2 = ax2.bar(x, [tokens_classic, tokens_repograph], width=bar_w,
                color=[CLASSIC_COLOR, REPOGRAPH_COLOR],
                edgecolor="none", zorder=3)
style_ax(ax2, "Prompt Tokens", "tokens")
ax2.set_ylim(0, tokens_classic * 1.45)

for bar, val in zip(bars2, [tokens_classic, tokens_repograph]):
    ax2.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 400,
             f"{val:,}", ha="center", va="bottom",
             color=TEXT_COLOR, fontsize=11, fontweight="bold")

ratio_tokens = tokens_classic / tokens_repograph
ax2.text(0.5, 0.88, f"{ratio_tokens:.1f}× fewer tokens",
         transform=ax2.transAxes, ha="center",
         color="#a8d8a8", fontsize=11, fontweight="bold")

# ── Legend / title ───────────────────────────────────────────────────────────

legend_handles = [
    mpatches.Patch(color=CLASSIC_COLOR,   label="Classic keyword agent"),
    mpatches.Patch(color=REPOGRAPH_COLOR, label="Scrooge agent"),
]
fig.legend(handles=legend_handles, loc="lower center", ncol=2,
           frameon=False, labelcolor=TEXT_COLOR, fontsize=10,
           bbox_to_anchor=(0.5, -0.02))

fig.suptitle("Scrooge vs Classic Agent — brian2 benchmark\n"
             "Query: \"explain function run in brian2 simulator\"",
             color=TEXT_COLOR, fontsize=13, fontweight="bold", y=1.02)

plt.tight_layout()
fig.savefig(OUTPUT_FILE, dpi=160, bbox_inches="tight",
            facecolor=BG_COLOR)
print(f"Saved: {OUTPUT_FILE}")
