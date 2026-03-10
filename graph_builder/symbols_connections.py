import networkx as nx

def generate_complete_connections(symbol_list: list, graph: nx.DiGraph, depth: int = 2):
    connections_list = []
    visited = set()

    start_nodes = [
        s["name"] for s in symbol_list
        if s["type"] in ["function", "method"]
    ]

    for start in start_nodes:

        if start not in graph:
            continue

        frontier = {start}

        for _ in range(depth):

            next_frontier = set()

            for node in frontier:

                if node in visited:
                    continue

                visited.add(node)

                for _, target in graph.out_edges(node):
                    connections_list.append({
                        "from": node,
                        "to": target,
                        "type": "calls"
                    })
                    next_frontier.add(target)

                for source, _ in graph.in_edges(node):
                    connections_list.append({
                        "from": source,
                        "to": node,
                        "type": "calls"
                    })
                    next_frontier.add(source)

            frontier = next_frontier

    return connections_list