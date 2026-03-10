import json
import re

def tokenize(s):
    parts = re.split(r"[._]", s)
    camel_parts = re.findall(r'[A-Z][^A-Z]*', s)
    return [p.lower() for p in parts + camel_parts if p]

def _matches(tokens, *parts):
    if not tokens:
        return True
    for part in parts:
        if not part:
            continue
        lower_part = part.lower()
        if lower_part in tokens:
            return True
        for token in tokens:
            if token in lower_part:
                return True
    return False


def symbol_extractor(query: str, parsed_json: str):
    tokens = {t.lower() for t in query.split()} if query else set()
    data = json.loads(parsed_json)
    files = data.get("parsed_repo", {}).get("files", {})

    symbol_list = []

    for file_name, file_data in files.items():
        functions = file_data.get("functions", {})
        for function_name in functions.keys():
            if _matches(tokens, function_name, file_name):
                symbol_list.append(
                    {
                        "name": function_name,
                        "type": "function",
                        "file": file_name,
                    }
                )

        classes = file_data.get("classes", {})
        for class_name, class_data in classes.items():
            methods = class_data.get("methods", {})
            for method_name in methods.keys():
                if _matches(tokens, method_name, class_name, file_name):
                    symbol_list.append(
                        {
                            "name": method_name,
                            "type": "method",
                            "class": class_name,
                            "file": file_name,
                        }
                    )

    return symbol_list