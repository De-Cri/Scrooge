# Benchmarks for RepoGraph

This folder contains an automated benchmark suite that evaluates RepoGraph on:

- Agent comparison (baseline repo scan vs RepoGraph CLI for time + token estimate)
- Correctness (nodes + edges vs expected graph on `example_repo`)
- Query utility (symbol matches for real queries)
- Context reduction (how much code is filtered out by queries)
- Performance scaling (time vs repo size on synthetic repos)

## How To Run

From the repo root:

```bash
python benchmarks/run_benchmarks.py
```

Results are printed to stdout and saved to:

`benchmarks/results/benchmark_results.json`

Generate a markdown report:

```bash
python benchmarks/report.py
```

The report is saved to:

`benchmarks/results/benchmark_report.md`

SVG charts are saved to:

- `benchmarks/results/agent_token_reduction_<repo>.svg`
- `benchmarks/results/agent_read_time_reduction_<repo>.svg`
- `benchmarks/results/agent_cli_time_<repo>.svg`
- `benchmarks/results/gemini_baseline_tokens_<repo>.svg`
- `benchmarks/results/gemini_repograph_tokens_<repo>.svg`

## What The Benchmarks Mean

- `agent_comparison`: baseline vs RepoGraph CLI for token estimates, read-time estimates, and CLI runtime.

## Notes

- The expected graph for `example_repo` lives in `benchmarks/fixtures/expected_example_repo.json`.
- Synthetic repos are created under `benchmarks/tmp/` and can be deleted safely.
- End-to-end time uses a simple estimate based on words per line and reading speed.
- Token estimates use a simple chars-per-token heuristic.
- Agent comparison baseline uses a simple keyword retrieval (top-k files by query terms).

## Real Repos

To benchmark real repositories, copy `benchmarks/real_repos.sample.json` to
`benchmarks/real_repos.json` and edit the paths + queries.

If `benchmarks/real_repos.json` exists, it will be used. Otherwise the benchmark
falls back to `example_repo`.

## Gemini Agent Benchmark (Real Agent)

This runs a real LLM (Gemini) per query with two agent modes:

- `classic`: keyword search over files
- `repograph`: keywords -> `architecture` + `connections`

Agent flow options:

- `single` (default): 1 round per agent (1 LLM call per agent)
- `agent`: realistic loop  
  `query → planning → search → open files → reasoning → search → open files → answer`

Set your API key:

```powershell
$env:GEMINI_API_KEY="YOUR_KEY"
```

Run:

```bash
.\.venv\Scripts\python.exe benchmarks/gemini_agent_benchmark.py --model gemini-2.5-flash --max-input-tokens 200000 --agent-flow single --agents repograph
```

Results are saved to:

`benchmarks/results/gemini_agent_results.json`

Notes:
- `--sleep-seconds` defaults to `0`. Increase if you hit rate limits.
- The output now stores per-query results under `agents` (`classic` and `repograph`).
- Use `--agent-flow agent` if you want the multi-step loop.
- Use `--agents classic|repograph|both` to control how many calls are made.
- Use `--arch-filter connections|none` to filter architecture matches by connection modules.
- Use `--rank-keep-pct 0.3` to keep only the top 30% of ranked nodes in connections.
- Use `--debug-files` to include the selected file lists in the JSON output.
