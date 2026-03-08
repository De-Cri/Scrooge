from parser import parse_file
from scanner import scan_repo
from graph_builder import build_graph
from output_writer import write_run_output

if __name__ == "__main__":
    files = scan_repo("example_repo")
    parsed_repo = {"files": {}}

    for file in files:
        if file.suffix == ".py":
            parsed_file = parse_file(file)
            parsed_repo["files"].update(parsed_file.get("files", {}))

    graph = build_graph(parsed_repo)
    output_path = write_run_output(parsed_repo, graph)
    print(f"Output scritto in: {output_path}")
