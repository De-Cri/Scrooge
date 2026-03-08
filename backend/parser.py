import ast
from pathlib import Path


def _build_import_map(tree, current_module):
    import_map = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                key = alias.asname or alias.name
                import_map[key] = alias.name
        elif isinstance(node, ast.ImportFrom):
            #base module
            module = node.module
            
            #managing relative imports
            if node.level > 0:
                parts = current_module.split(".")
                base = parts[:-node.level]
                if module:
                    module = ".".join(base + [module])
                else:
                    module = ".".join(base)

            for alias in node.names:
                key = alias.asname or alias.name
                import_map[key] = f"{module}.{alias.name}" if module else alias.name

    return import_map


def _get_local_symbols(tree):
    functions = set()
    classes = {}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            methods = {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            classes[node.name] = methods

    return functions, classes


def _get_attr_chain(attr_node):
    parts = []
    current = attr_node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return list(reversed(parts))
    return None


def _qualify_name(
    name,
    module_name,
    import_map,
    local_functions,
    class_name=None,
    class_methods=None,
):
    if name in import_map:
        return import_map[name]
    if class_name and class_methods and name in class_methods:
        return f"{module_name}.{class_name}.{name}"
    if name in local_functions:
        return f"{module_name}.{name}"
    return name


def _extract_calls(
    node,
    module_name,
    import_map,
    local_functions,
    class_name=None,
    class_methods=None,
):
    calls = []

    for subnode in ast.walk(node):
        if not isinstance(subnode, ast.Call):
            continue

        func = subnode.func

        if isinstance(func, ast.Name):
            calls.append(
                _qualify_name(
                    func.id,
                    module_name,
                    import_map,
                    local_functions,
                    class_name,
                    class_methods,
                )
            )
            continue

        if isinstance(func, ast.Attribute):
            chain = _get_attr_chain(func)
            if not chain:
                continue

            if chain[0] == "self" and class_name:
                calls.append(f"{module_name}.{class_name}.{'.'.join(chain[1:])}")
                continue

            base = chain[0]
            if base in import_map:
                calls.append(f"{import_map[base]}.{'.'.join(chain[1:])}")
            else:
                calls.append(".".join(chain))

    return calls


def parse_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    path_obj = Path(file_path)
    module_name = path_obj.stem
    file_name = path_obj.name

    # Build a Python-like module path (e.g. package.subpackage.module)
    try:
        rel_path = path_obj.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        rel_path = path_obj

    module_parts = list(rel_path.with_suffix("").parts)
    if module_parts and module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    current_module = ".".join(module_parts) if module_parts else module_name

    import_map = _build_import_map(tree, current_module)
    local_functions, class_map = _get_local_symbols(tree)

    parsed_file = {"classes": {}, "functions": {}}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parsed_file["functions"][node.name] = {
                "calls": _extract_calls(
                    node,
                    module_name,
                    import_map,
                    local_functions,
                )
            }

        elif isinstance(node, ast.ClassDef):
            methods = {}
            class_methods = class_map.get(node.name, set())

            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods[item.name] = {
                        "calls": _extract_calls(
                            item,
                            module_name,
                            import_map,
                            local_functions,
                            class_name=node.name,
                            class_methods=class_methods,
                        )
                    }

            parsed_file["classes"][node.name] = {"methods": methods}

    return {"files": {file_name: parsed_file}}
