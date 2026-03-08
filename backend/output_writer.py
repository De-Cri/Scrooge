import json
from pathlib import Path


def write_run_output(parsed_repo, graph, output_path=None):
    repo_root = Path(__file__).resolve().parent.parent
    default_path = repo_root / "output" / "graph_output.json"
    target_path = Path(output_path) if output_path else default_path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "parsed_repo": parsed_repo,
        "graph": {
            "nodes": list(graph.nodes()),
            "edges": [{"source": src, "target": dst} for src, dst in graph.edges()],
        },
    }

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return target_path
