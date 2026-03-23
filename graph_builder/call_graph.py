import networkx as nx
from pathlib import Path


def _resolve_call(call, internal_nodes):
    """Strip package prefix from a call target to match a stem-based internal node.

    The parser resolves imports with full package paths
    (e.g. ``notifications.emailer.send_welcome_email``) but nodes are created
    using only the file stem (e.g. ``emailer.send_welcome_email``).
    This function progressively removes leading dotted segments until it finds
    a match in *internal_nodes*, or returns the original string unchanged.
    """
    if call in internal_nodes:
        return call
    parts = call.split(".")
    # Try removing one leading segment at a time: a.b.c.d → b.c.d → c.d
    for i in range(1, len(parts)):
        candidate = ".".join(parts[i:])
        if candidate in internal_nodes:
            return candidate
    return call


def build_graph(parsed_data):
    graph = nx.DiGraph()
    internal_nodes = set()
    files = parsed_data.get("files", {}) if isinstance(parsed_data, dict) else {}

    # --- Pass 1: create all nodes so internal_nodes is complete ---
    pending_edges = []
    for file_name, file_data in files.items():
        module_name = Path(file_name).stem

        for function_name, function_data in file_data.get("functions", {}).items():
            source = f"{module_name}.{function_name}"
            graph.add_node(source)
            internal_nodes.add(source)
            for call in function_data.get("calls", []):
                pending_edges.append((source, call))

        for class_name, class_data in file_data.get("classes", {}).items():
            methods = class_data.get("methods", {})
            for method_name, method_data in methods.items():
                source = f"{module_name}.{class_name}.{method_name}"
                graph.add_node(source)
                internal_nodes.add(source)
                for call in method_data.get("calls", []):
                    pending_edges.append((source, call))

    # --- Pass 2: add edges, resolving package-prefixed targets ---
    for source, call in pending_edges:
        graph.add_edge(source, _resolve_call(call, internal_nodes))

    graph.graph["internal_nodes"] = internal_nodes
    return graph
