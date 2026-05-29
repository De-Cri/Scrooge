import json
import re

def tokenize(s):
    parts = re.split(r"[^A-Za-z0-9]+", s)
    camel_parts = re.findall(r"[A-Z][^A-Z]*", s)
    return [p.lower() for p in parts + camel_parts if p]

def _matches(query_tokens, *parts):
    if not query_tokens:
        return True
    for part in parts:
        if not part:
            continue
        lower_part = part.lower()
        for q in query_tokens:
            if q in lower_part:
                return True
    return False

def _token_overlap(query_tokens, candidate_tokens):
    for q in query_tokens:
        for c in candidate_tokens:
            if c in q or q in c:
                return True
    return False


def _count_matched_tokens(query_tokens, names: list) -> int:
    """Count how many distinct query tokens appear in any of the given names."""
    matched = set()
    for name in names:
        lower = name.lower()
        for q in query_tokens:
            if q in lower:
                matched.add(q)
    return len(matched)


def symbol_extractor(query: str, parsed_json: str):
    """Return a map of file_name → matched symbols (with line numbers).

    Output schema:
        {
            "file.py": {
                "functions": {"func_name": {"line": 12}, ...},
                "classes": {
                    "ClassName": {
                        "methods": {"method_name": {"line": 34}, ...}
                    }
                }
            }
        }

    A function/method matches if any query token is a substring of its name,
    OR if the file name itself matches a query token (e.g. query "auth" picks
    up everything in auth.py).

    Each matched file also gets a ``token_coverage`` field (0.0–1.0): the
    fraction of distinct query tokens that appear in that file's symbols or
    name.  Files where more tokens match score higher and should be preferred
    by the caller when ranking candidates.
    """
    token_list = tokenize(query) if query else []
    tokens = set(token_list)
    data = json.loads(parsed_json)
    files = data.get("parsed_repo", {}).get("files", {})

    symbol_map = {}
    coverage_map = {}  # file_name -> fraction of tokens matched

    for file_name, file_data in files.items():
        file_tokens = set(tokenize(file_name))
        file_match = _token_overlap(tokens, file_tokens)

        functions = file_data.get("functions", {})
        for function_name, function_info in functions.items():
            if file_match or _matches(tokens, function_name):
                file_bucket = symbol_map.setdefault(file_name, {})
                fn_bucket = file_bucket.setdefault("functions", {})
                fn_bucket[function_name] = {"line": function_info.get("line")}

        classes = file_data.get("classes", {})
        for class_name, class_data in classes.items():
            methods = class_data.get("methods", {})
            for method_name, method_info in methods.items():
                if file_match or _matches(tokens, method_name):
                    file_bucket = symbol_map.setdefault(file_name, {})
                    classes_bucket = file_bucket.setdefault("classes", {})
                    class_bucket = classes_bucket.setdefault(class_name, {})
                    methods_bucket = class_bucket.setdefault("methods", {})
                    methods_bucket[method_name] = {"line": method_info.get("line")}

    # Compute token coverage per matched file
    n_tokens = max(1, len(tokens))
    for file_name in symbol_map:
        file_data_raw = files.get(file_name, {})
        all_names = (
            [file_name]
            + list(file_data_raw.get("functions", {}).keys())
            + list(file_data_raw.get("classes", {}).keys())
            + [
                m
                for cls_data in file_data_raw.get("classes", {}).values()
                for m in cls_data.get("methods", {}).keys()
            ]
        )
        coverage_map[file_name] = _count_matched_tokens(tokens, all_names) / n_tokens

    ordered_map = {}
    for file_name in sorted(symbol_map.keys()):
        file_data = symbol_map[file_name]
        ordered_file = {}

        if "functions" in file_data:
            ordered_file["functions"] = {
                name: file_data["functions"][name]
                for name in sorted(file_data["functions"])
            }

        if "classes" in file_data:
            classes_ordered = {}
            for class_name in sorted(file_data["classes"].keys()):
                class_data = file_data["classes"][class_name]
                class_ordered = {}
                if "methods" in class_data:
                    class_ordered["methods"] = {
                        name: class_data["methods"][name]
                        for name in sorted(class_data["methods"])
                    }
                if class_ordered:
                    classes_ordered[class_name] = class_ordered
            if classes_ordered:
                ordered_file["classes"] = classes_ordered

        if ordered_file:
            ordered_file["_token_coverage"] = round(coverage_map.get(file_name, 0.0), 3)
            ordered_map[file_name] = ordered_file

    return ordered_map
