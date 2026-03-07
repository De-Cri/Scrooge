# RepoGraph

**Understand any codebase in seconds.**

RepoGraph scans a repository and builds a **function-level dependency graph** so you can instantly see how functions, files, and modules interact.

Designed for developers working with **large codebases** and AI coding tools like Claude Code.

---

## Why RepoGraph?

Modern AI coding tools struggle with **large repositories** because they need to read thousands of lines of code to understand context.

RepoGraph solves this by creating a **structural map of the repository**, showing:

* which functions call each other
* how modules interact
* what parts of the code will be affected by a change

Instead of reading the whole codebase, an AI (or developer) can query the graph and instantly understand **the relevant parts of the system**.

---

## Example

Imagine this code:

```python
def login(user):
    authenticate(user)

def authenticate(user):
    get_user(user)

def get_user(user):
    pass
```

RepoGraph builds this call graph:

```
login → authenticate → get_user
```

Now you immediately know:

* changing `get_user()` impacts `authenticate()` and `login()`
* `login()` is the entry point

---

## Features

* Repository scanning
* Function-level dependency graph
* Call graph generation
* CLI interface
* Lightweight and fast

Planned features:

* cross-file dependency graphs
* class & method analysis
* impact analysis (`what breaks if I change this?`)
* integration with AI coding agents
* persistent context files for large codebases

---

## Installation

Clone the repository:

```bash
git clone https://github.com/yourname/repograph
cd repograph
```

Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install typer networkx
```

---

## Usage

Run RepoGraph on a repository:

```bash
python cli.py index path/to/repository
```

Example output:

```
Nodes: ['login', 'authenticate', 'get_user']
Edges: [('login', 'authenticate'), ('authenticate', 'get_user')]
```

---

## Architecture

RepoGraph is built with three main components.

### Scanner

Finds all source files in the repository.

```
repo → files
```

---

### Parser

Extracts:

* functions
* function calls
* relationships

```
file → functions → calls
```

---

### Graph Builder

Builds a dependency graph using NetworkX.

```
functions → graph
```

---

## Project Structure

```
repograph
│
├─ scanner.py
├─ parser.py
├─ graph_builder.py
├─ cli.py
│
└─ example_repo
   └─ auth.py
```

---

## Future Vision

RepoGraph could become the **structural memory layer for AI coding agents**.

Instead of reading entire repositories, agents could:

* query the dependency graph
* fetch only relevant code
* reason about impact before editing code

This makes large repositories **much easier to navigate, modify, and maintain**.

---

## Contributing

Contributions are welcome.

If you have ideas for:

* better parsing
* language support
* graph visualization
* AI integrations

open an issue or submit a pull request.

---

## License

MIT
