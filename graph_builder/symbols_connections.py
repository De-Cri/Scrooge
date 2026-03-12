import math
import networkx as nx

from intelligence.rank_graph_connections import rank_graph_nodes

def generate_complete_connections(
    symbol_list: list,
    graph: nx.DiGraph,
    depth: int,
    max_nodes: int = 40,
    rank_keep_pct: float = 1.0,
    return_ranked: bool = False,
):
    connections_list = []
    visited = set()

    start_nodes = [
        s["name"] for s in symbol_list
        if s["type"] in ["function", "method"]
    ]

    ranked_graph = graph
    ranked_nodes = []

    if start_nodes:
        existing_starts = [node for node in start_nodes if node in graph]
        if existing_starts:
            ranked_nodes = rank_graph_nodes(
                graph,
                existing_starts,
                max_nodes=max_nodes,
            )
            if ranked_nodes:
                if 0 < rank_keep_pct < 1:
                    keep_count = max(1, int(math.ceil(len(ranked_nodes) * rank_keep_pct)))
                    ranked_nodes = ranked_nodes[:keep_count]
                ranked_graph = graph.subgraph(ranked_nodes)

    for start in start_nodes:

        if start not in ranked_graph:
            continue

        frontier = {start}

        for current_depth in range(depth):

            next_frontier = set()

            for node in frontier:

                if node in visited:
                    continue

                visited.add(node)

                for _, target in ranked_graph.out_edges(node):
                    connections_list.append({
                        "from": node,
                        "to": target,
                        "type": "calls",
                        "depth": current_depth + 1
                    })
                    next_frontier.add(target)

                for source, _ in ranked_graph.in_edges(node):
                    connections_list.append({
                        "from": source,
                        "to": node,
                        "type": "calls",
                        "depth": current_depth + 1
                    })
                    next_frontier.add(source)

            frontier = next_frontier

    if return_ranked:
        return connections_list, ranked_nodes

    return connections_list
