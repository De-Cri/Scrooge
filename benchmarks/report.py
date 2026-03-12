import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_svg(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def _svg_header(width, height):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'


def _svg_footer():
    return "</svg>"


def _svg_bar_chart(title, labels, values, max_value, width=900, height=320):
    padding = 50
    chart_w = width - padding * 2
    chart_h = height - padding * 2
    bar_gap = 16
    bar_width = (chart_w - bar_gap * (len(values) - 1)) / max(1, len(values))
    lines = [_svg_header(width, height)]
    lines.append(f'<rect width="100%" height="100%" fill="#0b0c10"/>')
    lines.append(f'<text x="{padding}" y="{padding - 16}" fill="#ffffff" font-size="16" font-family="Arial">{title}</text>')
    for i, (label, value) in enumerate(zip(labels, values)):
        x = padding + i * (bar_width + bar_gap)
        h = 0 if max_value <= 0 else (value / max_value) * chart_h
        y = padding + (chart_h - h)
        lines.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{h:.2f}" fill="#66fcf1"/>')
        lines.append(f'<text x="{x + bar_width/2:.2f}" y="{padding + chart_h + 18}" fill="#c5c6c7" font-size="12" text-anchor="middle" font-family="Arial">{label}</text>')
        lines.append(f'<text x="{x + bar_width/2:.2f}" y="{y - 6:.2f}" fill="#ffffff" font-size="12" text-anchor="middle" font-family="Arial">{value}</text>')
    lines.append(_svg_footer())
    return "\n".join(lines)


def _svg_line_chart(title, labels, values, max_value, width=900, height=320):
    padding = 50
    chart_w = width - padding * 2
    chart_h = height - padding * 2
    lines = [_svg_header(width, height)]
    lines.append(f'<rect width="100%" height="100%" fill="#0b0c10"/>')
    lines.append(f'<text x="{padding}" y="{padding - 16}" fill="#ffffff" font-size="16" font-family="Arial">{title}</text>')
    points = []
    for i, value in enumerate(values):
        x = padding + (i / max(1, len(values) - 1)) * chart_w
        h = 0 if max_value <= 0 else (value / max_value) * chart_h
        y = padding + (chart_h - h)
        points.append((x, y))
    if points:
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)
        lines.append(f'<path d="{path}" fill="none" stroke="#45a29e" stroke-width="3"/>')
        for (x, y), label, value in zip(points, labels, values):
            lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#66fcf1"/>')
            lines.append(f'<text x="{x:.2f}" y="{padding + chart_h + 18}" fill="#c5c6c7" font-size="12" text-anchor="middle" font-family="Arial">{label}</text>')
            lines.append(f'<text x="{x:.2f}" y="{y - 8:.2f}" fill="#ffffff" font-size="12" text-anchor="middle" font-family="Arial">{value}</text>')
    lines.append(_svg_footer())
    return "\n".join(lines)


def _bar(value, max_value, width=24):
    if max_value <= 0:
        return ""
    filled = int(round((value / max_value) * width))
    filled = max(0, min(width, filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def _section(title, body):
    return f"**{title}**\n{body}"


def _find_agent(item, agent_name):
    for agent in item.get("agents", []):
        if agent.get("agent") == agent_name:
            return agent
    return {}


def _agent_prompt_tokens(agent):
    usage = agent.get("final", {}).get("response", {}).get("usage", {})
    return usage.get("prompt_token_count")


def _agent_files_used(agent):
    return agent.get("final", {}).get("files_used")


def main():
    results_path = REPO_ROOT / "benchmarks" / "results" / "benchmark_results.json"
    if not results_path.exists():
        raise SystemExit("Run benchmarks first: python benchmarks/run_benchmarks.py")

    data = json.loads(results_path.read_text(encoding="utf-8"))
    gemini_path = REPO_ROOT / "benchmarks" / "results" / "gemini_agent_results.json"
    gemini_data = None
    if gemini_path.exists():
        gemini_data = json.loads(gemini_path.read_text(encoding="utf-8"))
    report_lines = []

    report_lines.append("# RepoGraph Benchmark Report")
    report_lines.append("")
    report_lines.append(f"Source: `{results_path}`")
    report_lines.append("")

    agent = data.get("agent_comparison", {})
    results_dir = results_path.parent

    agent_repos = agent.get("repos", [])
    for repo in agent_repos:
        repo_name = repo.get("name", "repo")
        agent_rows = []
        for item in repo.get("results", []):
            agent_rows.append(
                (
                    item.get("query"),
                    item.get("baseline", {}).get("tokens_estimate"),
                    item.get("repograph", {}).get("tokens_estimate"),
                    item.get("savings", {}).get("token_reduction"),
                    item.get("savings", {}).get("read_time_reduction"),
                    item.get("repograph", {}).get("architecture_time_s"),
                    item.get("repograph", {}).get("connections_time_s"),
                )
            )
        agent_table = _table(
            [
                "query",
                "baseline_tokens",
                "repograph_tokens",
                "token_reduction",
                "read_time_reduction",
                "arch_time_s",
                "conn_time_s",
            ],
            agent_rows,
        )
        report_lines.append(_section(f"Agent Comparison ({repo_name})", agent_table))
        report_lines.append("")

        # Agent comparison charts per repo
        agent_labels = [r.get("query") for r in repo.get("results", [])]
        token_reduction_vals = [r.get("savings", {}).get("token_reduction", 0) for r in repo.get("results", [])]
        token_reduction_svg = _svg_bar_chart(
            f"Token Reduction ({repo_name})",
            agent_labels,
            token_reduction_vals,
            1.0,
        )
        token_reduction_path = results_dir / f"agent_token_reduction_{repo_name}.svg"
        _write_svg(token_reduction_path, token_reduction_svg)
        report_lines.append(f'![Agent Token Reduction {repo_name}]({token_reduction_path.as_posix()})')
        report_lines.append("")

        read_time_reduction_vals = [r.get("savings", {}).get("read_time_reduction", 0) for r in repo.get("results", [])]
        read_time_svg = _svg_bar_chart(
            f"Read Time Reduction ({repo_name})",
            agent_labels,
            read_time_reduction_vals,
            1.0,
        )
        read_time_path = results_dir / f"agent_read_time_reduction_{repo_name}.svg"
        _write_svg(read_time_path, read_time_svg)
        report_lines.append(f'![Agent Read Time Reduction {repo_name}]({read_time_path.as_posix()})')
        report_lines.append("")

        total_time_vals = [
            (r.get("repograph", {}).get("architecture_time_s", 0) + r.get("repograph", {}).get("connections_time_s", 0))
            for r in repo.get("results", [])
        ]
        total_time_svg = _svg_bar_chart(
            f"RepoGraph CLI Time ({repo_name})",
            agent_labels,
            total_time_vals,
            max(total_time_vals) if total_time_vals else 0,
        )
        total_time_path = results_dir / f"agent_cli_time_{repo_name}.svg"
        _write_svg(total_time_path, total_time_svg)
        report_lines.append(f'![Agent CLI Time {repo_name}]({total_time_path.as_posix()})')
        report_lines.append("")

    if gemini_data:
        report_lines.append("**Gemini Agent Comparison (Real Model)**")
        report_lines.append(f"Source: `{gemini_path}`")
        report_lines.append("")

        for repo in gemini_data.get("results", []):
            repo_name = repo.get("name", "repo")
            rows = []
            for item in repo.get("queries", []):
                if "agents" in item:
                    classic = _find_agent(item, "classic")
                    repograph = _find_agent(item, "repograph")
                    base_prompt = _agent_prompt_tokens(classic)
                    repo_prompt = _agent_prompt_tokens(repograph)
                    base_files = _agent_files_used(classic)
                    repo_files = _agent_files_used(repograph)
                else:
                    base_usage = item.get("baseline", {}).get("response", {}).get("usage", {})
                    repo_usage = item.get("repograph", {}).get("response", {}).get("usage", {})
                    base_prompt = base_usage.get("prompt_token_count")
                    repo_prompt = repo_usage.get("prompt_token_count")
                    base_files = item.get("baseline", {}).get("files_used")
                    repo_files = item.get("repograph", {}).get("files_used")
                rows.append(
                    (
                        item.get("query"),
                        base_prompt,
                        repo_prompt,
                        base_files,
                        repo_files,
                    )
                )
            report_lines.append(_section(f"Gemini ({repo_name})", _table(
                ["query", "baseline_prompt_tokens", "repograph_prompt_tokens", "baseline_files", "repograph_files"],
                rows,
            )))
            report_lines.append("")

            labels = [r.get("query") for r in repo.get("queries", [])]
            if repo.get("queries") and "agents" in repo.get("queries", [])[0]:
                base_vals = [
                    _agent_prompt_tokens(_find_agent(r, "classic")) or 0
                    for r in repo.get("queries", [])
                ]
                repo_vals = [
                    _agent_prompt_tokens(_find_agent(r, "repograph")) or 0
                    for r in repo.get("queries", [])
                ]
            else:
                base_vals = [
                    r.get("baseline", {}).get("response", {}).get("usage", {}).get("prompt_token_count", 0)
                    for r in repo.get("queries", [])
                ]
                repo_vals = [
                    r.get("repograph", {}).get("response", {}).get("usage", {}).get("prompt_token_count", 0)
                    for r in repo.get("queries", [])
                ]

            max_val = max(base_vals + repo_vals) if (base_vals or repo_vals) else 0
            base_svg = _svg_bar_chart(f"Gemini Baseline Prompt Tokens ({repo_name})", labels, base_vals, max_val)
            repo_svg = _svg_bar_chart(f"Gemini RepoGraph Prompt Tokens ({repo_name})", labels, repo_vals, max_val)

            base_path = results_dir / f"gemini_baseline_tokens_{repo_name}.svg"
            repo_path = results_dir / f"gemini_repograph_tokens_{repo_name}.svg"
            _write_svg(base_path, base_svg)
            _write_svg(repo_path, repo_svg)

            report_lines.append(f'![Gemini Baseline Tokens {repo_name}]({base_path.as_posix()})')
            report_lines.append("")
            report_lines.append(f'![Gemini RepoGraph Tokens {repo_name}]({repo_path.as_posix()})')
            report_lines.append("")

    out_path = REPO_ROOT / "benchmarks" / "results" / "benchmark_report.md"
    out_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Report written to: {out_path}")


if __name__ == "__main__":
    main()
