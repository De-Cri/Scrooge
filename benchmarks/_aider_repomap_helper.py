"""
Helper: generates Aider repo map via subprocess (aider venv Python 3.11).
"""
import sys, json, re
from pathlib import Path

repo_path    = sys.argv[1]
trigger_file = sys.argv[2] if len(sys.argv) > 2 else ""
max_tokens   = int(sys.argv[3]) if len(sys.argv) > 3 else 2048

_EXCLUDE = re.compile(
    r"([\\/]tests?[\\/]|[\\/]examples?[\\/]|[\\/]dev[\\/]"
    r"|test_[^/\\]*\.py$|_test\.py$|conftest\.py$|setup\.py$)"
)

class FakeModel:
    """Minimal model mock so RepoMap can count tokens without an API key."""
    def token_count(self, text):
        return len(str(text)) // 4
    def token_count_for_image(self, *a):
        return 0
    info = {"max_tokens": 8192}

try:
    from aider.repomap import RepoMap
    from aider.io import InputOutput

    io_obj = InputOutput(yes=True)

    # Patch RepoMap to accept our fake model
    rm = RepoMap.__new__(RepoMap)
    rm.io = io_obj
    rm.root = repo_path
    rm.map_tokens = max_tokens
    rm.max_context_window = max_tokens * 2
    rm.main_model = FakeModel()
    rm.verbose = False
    rm.tree_cache = {}
    rm.tree_context_cache = {}
    rm.map_cache = {}
    rm.map_processing_time = 0
    rm.token_count = FakeModel().token_count
    rm.CACHE_VERSION = 3
    rm.cache_missing = False

    # Use the proper __init__ path instead
    rm2 = RepoMap(
        map_tokens=max_tokens,
        root=repo_path,
        main_model=FakeModel(),
        io=io_obj,
        verbose=False,
    )

    other_files = [
        str(f) for f in sorted(Path(repo_path).rglob("*.py"))
        if not _EXCLUDE.search(str(f).replace("\\", "/"))
    ][:300]

    chat_files = []
    if trigger_file and Path(trigger_file).exists():
        chat_files = [trigger_file]

    repo_map = rm2.get_repo_map(chat_files, other_files) or ""

    print(json.dumps({
        "repomap": repo_map,
        "tokens": max(1, len(repo_map) // 4),
        "lines": len(repo_map.splitlines()),
        "error": None,
    }))

except Exception as e:
    import traceback
    print(json.dumps({"repomap": "", "tokens": 0, "lines": 0, "error": str(e) + "\n" + traceback.format_exc()}))
