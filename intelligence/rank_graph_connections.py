import networkx as nx


def rank_graph_nodes(graph, start_nodes, max_nodes=40, return_scores=False):
    internal_nodes = graph.graph.get("internal_nodes", set(graph.nodes()))
    working_graph = graph.subgraph(internal_nodes)

    # Reverse view used to also reach callers (predecessors) of the start nodes.
    # Without this, a query that matches a leaf-y function only ranks the start
    # itself, and the architecture output is empty for that file.
    reverse_graph = working_graph.reverse(copy=False)

    distances = {}

    for start in start_nodes:
        if start not in working_graph:
            continue
        # Forward: things this symbol calls (and their downstream).
        forward = nx.single_source_shortest_path_length(working_graph, start, cutoff=4)
        for node, d in forward.items():
            distances[node] = min(distances.get(node, 999), d)
        # Backward: things that call this symbol (and their upstream).
        backward = nx.single_source_shortest_path_length(reverse_graph, start, cutoff=4)
        for node, d in backward.items():
            distances[node] = min(distances.get(node, 999), d)

    reachable_subgraph = working_graph.subgraph(distances.keys())
    pagerank = nx.pagerank(reachable_subgraph, alpha=0.85)
    degree = dict(reachable_subgraph.degree())

    # Normalize PageRank and degree to [0, 1] so they meaningfully contribute
    # at any graph size (raw PageRank is ~1/N which is near-zero for large repos).
    max_pr = max(pagerank.values(), default=1) or 1
    max_deg = max(degree.values(), default=1) or 1

    scores = []

    for node in distances:

        dist = distances[node]

        score = (
            (1 / (dist + 1))
            + (pagerank.get(node, 0) / max_pr) * 0.3
            + (degree.get(node, 0) / max_deg) * 0.1
        )

        scores.append((score, node))

    scores.sort(reverse=True)

    ranked = scores[:max_nodes]

    if return_scores:
        return [(node, score) for score, node in ranked]

    return [node for _, node in ranked]