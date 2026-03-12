import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google import genai
from google.genai import errors
from benchmarks.bench_utils import (
    baseline_retrieval,
    build_basename_index,
    build_context,
    files_from_connections,
    read_file,
    resolve_selected_files,
    run_cli_json,
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_repos_config(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Repos config not found: {path}")
    data = _read_json(path)
    repos = data.get("repos", [])
    if not repos:
        raise ValueError("No repos configured in real_repos.json")
    return repos


def _count_tokens(client, model, text):
    resp = client.models.count_tokens(model=model, contents=text)

    for attr in ("total_tokens", "totalTokenCount", "total_token_count"):
        if hasattr(resp, attr):
            return getattr(resp, attr)

    if isinstance(resp, dict):
        return (
            resp.get("total_tokens")
            or resp.get("totalTokenCount")
            or resp.get("total_token_count")
        )

    return None


def _trim_to_token_limit(client, model, files, token_limit):
    if token_limit <= 0:
        return files, 0

    approx_char_limit = token_limit * 4

    kept = []
    total_chars = 0

    for path in files:
        text = read_file(path)
        size = len(text)

        if total_chars + size > approx_char_limit and kept:
            break

        kept.append(path)
        total_chars += size

    while kept:
        ctx = build_context(kept)
        token_count = _count_tokens(client, model, ctx)

        if token_count is None or token_count <= token_limit:
            return kept, token_count or 0

        kept = kept[:-1]

    return [], 0


def _build_prompt(task, context):
    return (
        "You are a senior software engineer. Use only the provided context to answer.\n\n"
        "Context:\n"
        f"{context}\n\n"
        f"Task: {task}\n"
        "Answer concisely and cite file paths when relevant."
    )


def _extract_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _fallback_keywords(query, max_terms=8):
    tokens = re.findall(r"[a-zA-Z0-9_]+", query.lower())
    keywords = []
    for token in tokens:
        if len(token) < 3:
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= max_terms:
            break
    if keywords:
        return keywords
    return tokens[:max_terms]


def _normalize_keywords(keywords, fallback_query, max_terms=8):
    if not keywords:
        return _fallback_keywords(fallback_query, max_terms=max_terms)
    cleaned = []
    for item in keywords:
        if not item:
            continue
        token = str(item).strip()
        if not token:
            continue
        cleaned.append(token)
        if len(cleaned) >= max_terms:
            break
    if cleaned:
        return cleaned
    return _fallback_keywords(fallback_query, max_terms=max_terms)


def _plan_search(client, model, task, mode):
    prompt = (
        "You are planning the first code search.\n"
        "Return ONLY valid JSON with this schema:\n"
        '{ "keywords": ["..."], "notes": "..." }\n'
        "Rules:\n"
        "- Provide 3 to 8 short keywords.\n"
        "- Use concrete terms (feature names, class names, modules).\n"
        "- Avoid stopwords and long phrases.\n"
        f"Search mode: {mode}.\n"
        f"Task: {task}\n"
    )

    resp = _run_model(client, model, prompt)
    data = _extract_json(resp.get("text", ""))
    keywords = _normalize_keywords(
        (data or {}).get("keywords"),
        fallback_query=task,
    )
    return {
        "keywords": keywords,
        "notes": (data or {}).get("notes", ""),
        "raw": resp.get("text", ""),
        "usage": resp.get("usage", {}),
    }


def _connection_modules(conn):
    modules = set()

    def add_node(node):
        if not node or "." not in node:
            return
        modules.add(node.split(".")[0] + ".py")

    nodes = (
        conn.get("rn")
        or conn.get("ranked_nodes")
        or conn.get("n", [])
    )
    for node in nodes:
        add_node(node)

    for edge in conn.get("e", []):
        if isinstance(edge, (list, tuple)) and len(edge) >= 2:
            add_node(edge[0])
            add_node(edge[1])

    return modules


def _reason_next_search(client, model, task, context, mode):
    prompt = (
        "You are mid-task. Use the context to decide what to search next.\n"
        "Return ONLY valid JSON with this schema:\n"
        '{ "summary": "...", "next_keywords": ["..."] }\n'
        "Rules:\n"
        "- Summary should be 1-2 short sentences.\n"
        "- Provide 2 to 6 short keywords for the next search.\n"
        f"Search mode: {mode}.\n"
        f"Task: {task}\n\n"
        "Context:\n"
        f"{context}\n"
    )

    resp = _run_model(client, model, prompt)
    data = _extract_json(resp.get("text", ""))
    next_keywords = _normalize_keywords(
        (data or {}).get("next_keywords"),
        fallback_query=task,
        max_terms=6,
    )
    return {
        "summary": (data or {}).get("summary", ""),
        "next_keywords": next_keywords,
        "raw": resp.get("text", ""),
        "usage": resp.get("usage", {}),
    }


def _run_model(client, model, prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            break

        except errors.ClientError as exc:

            if getattr(exc, "status_code", None) == 429 and attempt < max_retries - 1:
                time.sleep(20)
                continue

            raise

    usage = getattr(response, "usage_metadata", None)

    usage_data = {}

    if usage:
        for key in (
            "prompt_token_count",
            "candidates_token_count",
            "total_token_count",
        ):
            if hasattr(usage, key):
                usage_data[key] = getattr(usage, key)

    return {
        "text": getattr(response, "text", "") or "",
        "usage": usage_data,
    }


def _search_round(
    *,
    agent_mode,
    repo_path,
    search_keywords,
    query_fallback,
    all_files,
    depth,
    basename_index,
    arch_filter,
    rank_keep_pct,
):
    search_query = " ".join(search_keywords).strip() or query_fallback

    if agent_mode == "classic":
        candidates = baseline_retrieval(search_query, all_files)
        return {
            "search_query": search_query,
            "files": candidates,
            "arch_files": [],
            "conn_files": [],
            "repograph": None,
        }

    arch = run_cli_json(
        REPO_ROOT,
        [
            "architecture",
            str(repo_path),
            search_query,
        ],
    )

    conn = run_cli_json(
        REPO_ROOT,
        [
            "connections",
            str(repo_path),
            search_query,
            str(depth),
            "--compact",
            "--rank-keep-pct",
            str(rank_keep_pct),
        ],
    )

    arch_files_raw = resolve_selected_files(
        repo_path,
        arch.keys(),
        basename_index,
    )

    arch_files = arch_files_raw
    if arch_filter == "connections":
        allowed = _connection_modules(conn)
        if allowed:
            filtered = [path for path in arch_files_raw if path.name in allowed]
            if filtered:
                arch_files = filtered

    conn_files = files_from_connections(
        conn,
        basename_index,
    )

    selected_files = list(dict.fromkeys(arch_files + conn_files))

    return {
        "search_query": search_query,
        "files": selected_files,
        "arch_files": arch_files,
        "conn_files": conn_files,
        "repograph": {
            "arch_matches": len(arch.keys()),
            "arch_files_selected": len(arch_files),
            "ranked_nodes": len(conn.get("rn", [])) if "rn" in conn else len(conn.get("ranked_nodes", [])),
            "matched_nodes": len(conn.get("n", [])),
            "edges": len(conn.get("e", [])),
        },
    }


def _run_agent(
    *,
    client,
    model,
    agent_mode,
    agent_flow,
    repo_path,
    basename_index,
    all_files,
    query,
    depth,
    token_limit,
    sleep_seconds,
    arch_filter,
    rank_keep_pct,
    debug_files,
):
    mode_label = "keyword" if agent_mode == "classic" else "repograph"
    if agent_flow == "single":
        plan = {
            "keywords": _fallback_keywords(query),
            "notes": "single-pass",
            "raw": "",
            "usage": {},
        }
    else:
        plan = _plan_search(client, model, query, mode_label)
        time.sleep(sleep_seconds)

    round1 = _search_round(
        agent_mode=agent_mode,
        repo_path=repo_path,
        search_keywords=plan["keywords"],
        query_fallback=query,
        all_files=all_files,
        depth=depth,
        basename_index=basename_index,
        arch_filter=arch_filter,
        rank_keep_pct=rank_keep_pct,
    )

    round1_files = round1["files"]

    round1_context_files, round1_token_count = _trim_to_token_limit(
        client,
        model,
        round1_files,
        token_limit,
    )

    round1_context = build_context(round1_context_files)

    if agent_flow == "single":
        reasoning = None
        round2 = None
        combined_files = round1_files
        round2_files = []
    else:
        reasoning = _reason_next_search(
            client,
            model,
            query,
            round1_context,
            mode_label,
        )

        time.sleep(sleep_seconds)

        round2 = _search_round(
            agent_mode=agent_mode,
            repo_path=repo_path,
            search_keywords=reasoning["next_keywords"],
            query_fallback=query,
            all_files=all_files,
            depth=depth,
            basename_index=basename_index,
            arch_filter=arch_filter,
            rank_keep_pct=rank_keep_pct,
        )

        round2_files = [f for f in round2["files"] if f not in round1_files]

        combined_files = list(dict.fromkeys(round1_files + round2_files))

    final_files, final_token_count = _trim_to_token_limit(
        client,
        model,
        combined_files,
        token_limit,
    )

    final_context = build_context(final_files)
    final_prompt = _build_prompt(query, final_context)
    final_resp = _run_model(client, model, final_prompt)

    time.sleep(sleep_seconds)

    round1_out = {
        "round": 1,
        "keywords": plan["keywords"],
        "search_query": round1["search_query"],
        "files_selected": len(round1_files),
        "files_used": len(round1_context_files),
        "token_count_estimate": round1_token_count,
        "repograph": round1["repograph"],
    }

    if debug_files:
        round1_out["files_selected_list"] = [p.as_posix() for p in round1_files]
        round1_out["files_used_list"] = [p.as_posix() for p in round1_context_files]
        if agent_mode != "classic":
            round1_out["arch_files_list"] = [p.as_posix() for p in round1.get("arch_files", [])]
            round1_out["conn_files_list"] = [p.as_posix() for p in round1.get("conn_files", [])]

    rounds = [round1_out]

    if round2:
        round2_out = {
            "round": 2,
            "keywords": reasoning["next_keywords"],
            "search_query": round2["search_query"],
            "files_selected": len(round2["files"]),
            "files_new": len(round2_files),
            "repograph": round2["repograph"],
        }
        if debug_files:
            round2_out["files_selected_list"] = [p.as_posix() for p in round2["files"]]
            round2_out["files_new_list"] = [p.as_posix() for p in round2_files]
            if agent_mode != "classic":
                round2_out["arch_files_list"] = [p.as_posix() for p in round2.get("arch_files", [])]
                round2_out["conn_files_list"] = [p.as_posix() for p in round2.get("conn_files", [])]
        rounds.append(round2_out)

    result = {
        "agent": agent_mode,
        "flow": agent_flow,
        "plan": plan,
        "reasoning": reasoning,
        "rounds": rounds,
        "final": {
            "files_used": len(final_files),
            "token_count_estimate": final_token_count,
            "response": final_resp,
        },
    }

    if debug_files:
        result["final"]["files_used_list"] = [p.as_posix() for p in final_files]

    return result


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--repos",
        default=str(REPO_ROOT / "benchmarks" / "real_repos.json"),
    )

    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
    )

    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=100000,
    )

    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--agent-flow",
        choices=["single", "agent"],
        default="single",
        help="single=1 round (1 LLM call per agent), agent=multi-step loop",
    )

    parser.add_argument(
        "--agents",
        choices=["classic", "repograph", "both"],
        default="both",
        help="Which agents to run per query.",
    )

    parser.add_argument(
        "--arch-filter",
        choices=["none", "connections"],
        default="connections",
        help="Filter architecture matches by connections-derived modules.",
    )

    parser.add_argument(
        "--rank-keep-pct",
        type=float,
        default=0.3,
        help="Percentuale (0-1) dei nodi rankati da mantenere per connections.",
    )

    parser.add_argument(
        "--debug-files",
        action="store_true",
        help="Include file lists in the output for debugging.",
    )

    parser.add_argument(
        "--output",
        default=str(
            REPO_ROOT
            / "benchmarks"
            / "results"
            / "gemini_agent_results.json"
        ),
    )

    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise SystemExit(
            "Set GEMINI_API_KEY in your environment before running."
        )

    client = genai.Client(api_key=api_key)

    repos = _load_repos_config(Path(args.repos))

    results = []

    for repo in repos:

        repo_path = Path(repo["path"]).expanduser()

        if not repo_path.exists():

            results.append(
                {
                    "name": repo.get("name") or repo_path.name,
                    "path": str(repo_path),
                    "error": "path_not_found",
                }
            )

            continue

        basename_index = build_basename_index(repo_path)

        all_files = [p for p in repo_path.rglob("*.py") if p.is_file()]

        repo_out = {
            "name": repo.get("name") or repo_path.name,
            "path": str(repo_path),
            "model": args.model,
            "max_input_tokens": args.max_input_tokens,
            "queries": [],
        }

        for item in repo.get("queries", []):

            query = item.get("query", "")
            depth = item.get("depth", 2)

            selected_agents = []
            if args.agents in ("classic", "both"):
                selected_agents.append("classic")
            if args.agents in ("repograph", "both"):
                selected_agents.append("repograph")

            repo_out["queries"].append(
                {
                    "query": query,
                    "depth": depth,
                    "agents": [
                        _run_agent(
                            client=client,
                            model=args.model,
                            agent_mode=agent_mode,
                            agent_flow=args.agent_flow,
                            repo_path=repo_path,
                            basename_index=basename_index,
                            all_files=all_files,
                            query=query,
                            depth=depth,
                            token_limit=args.max_input_tokens,
                            sleep_seconds=args.sleep_seconds,
                            arch_filter=args.arch_filter,
                            rank_keep_pct=args.rank_keep_pct,
                            debug_files=args.debug_files,
                        )
                        for agent_mode in selected_agents
                    ],
                }
            )

        results.append(repo_out)

    out_path = Path(args.output)

    out_path.write_text(
        json.dumps({"results": results}, indent=2),
        encoding="utf-8",
    )

    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
