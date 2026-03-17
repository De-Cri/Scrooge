import networkx as nx
from pathlib import Path


def build_graph(parsed_data):
    graph = nx.DiGraph()
    internal_nodes = set()
    files = parsed_data.get("files", {}) if isinstance(parsed_data, dict) else {}

    for file_name, file_data in files.items():
        module_name = Path(file_name).stem

        for function_name, function_data in file_data.get("functions", {}).items():
            source = f"{module_name}.{function_name}"
            graph.add_node(source)
            internal_nodes.add(source)
            for call in function_data.get("calls", []):
                graph.add_edge(source, call)

        for class_name, class_data in file_data.get("classes", {}).items():
            methods = class_data.get("methods", {})
            for method_name, method_data in methods.items():
                source = f"{module_name}.{class_name}.{method_name}"
                graph.add_node(source)
                internal_nodes.add(source)
                for call in method_data.get("calls", []):
                    graph.add_edge(source, call)

    graph.graph["internal_nodes"] = internal_nodes
    return graph
