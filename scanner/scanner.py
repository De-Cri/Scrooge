import os
from pathlib import Path

SUPPORTED_EXT= [".py",".js",".ts"]

IGNORED_DIRS= {".git", "node_modules", "__pycache","dist","build",".venv"}

def scan_repo(root_path: str):
    files = []
    #os.walk is used to scrape useless dirs without diving into them
    for root, dirs, filenames in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for name in filenames:
            path = Path(root) / name
            if path.suffix in SUPPORTED_EXT:
                files.append(path)

    return files