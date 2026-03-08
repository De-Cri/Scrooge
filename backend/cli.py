import typer
from scanner import scan_repo
from parser import parse_file
from graph_builder import build_graph
from output_writer import write_run_output

app = typer.Typer()


@app.command()
def index(path: str):
    files = scan_repo(path)
    parsed_repo = {"files": {}}

    for file in files:
        if file.suffix == ".py":
            parsed_file = parse_file(file)
            parsed_repo["files"].update(parsed_file.get("files", {}))

    graph = build_graph(parsed_repo)
    output_path = write_run_output(parsed_repo, graph)
    typer.echo(f"Output scritto in: {output_path}")


if __name__ == "__main__":
    app()
