import networkx as nx


def rank_graph_nodes(graph, start_nodes, max_nodes=40):
    distances = {}

    for start in start_nodes:
        lengths = nx.single_source_shortest_path_length(graph, start, cutoff=4)
        for node, d in lengths.items():
            distances[node] = min(distances.get(node, 999), d)

    pagerank = nx.pagerank(graph, alpha=0.85)
    degree = dict(graph.degree())
    scores = []

    for node in distances:

        dist = distances[node]

        score = (
            (1 / (dist + 1))
            + pagerank.get(node, 0)
            + degree.get(node, 0) * 0.01
        )

        scores.append((score, node))

    scores.sort(reverse=True)

    return [node for _, node in scores[:max_nodes]]