


# index_meta.py
# Store metadata for the current search index.
# Save dataset information and key configuration values.
# Detect changes before loading the search index.
# Warn if the index is outdated and should be rebuilt.
# Prevent retrieval from using an old or mismatched index.


import json
import os

import config

# Settings that invalidate the index if changed, requiring a rebuild
TRACKED_SETTINGS = ["CHUNK_SIZE", "CHUNK_OVERLAP", "EMBEDDING_MODEL_NAME"]


def get_current_state():  # Get current state of dataset and settings
    file_info = {}
    if os.path.exists(config.SOURCE_FILE):
        stat = os.stat(config.SOURCE_FILE)
        file_info = {"size": stat.st_size, "mtime": int(stat.st_mtime)}

    settings = {name: getattr(config, name) for name in TRACKED_SETTINGS}

    return {"file": file_info, "settings": settings}


def save(n_chunks):  # Save state
    state = get_current_state()
    state["n_chunks"] = n_chunks
    state["source_file"] = os.path.basename(config.SOURCE_FILE)

    with open(config.INDEX_META_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def find_problems():  # Check for problems in index

    if not os.path.exists(config.INDEX_META_FILE):
        return []       # Never saved before, cannot check, but not considered an error

    try:
        with open(config.INDEX_META_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    now = get_current_state()
    problems = []

    if saved.get("file") != now["file"]:
        problems.append(f"File {os.path.basename(config.SOURCE_FILE)} was modified after building the index")

    for name in TRACKED_SETTINGS:
        old_value = saved.get("settings", {}).get(name)
        new_value = now["settings"][name]
        if old_value != new_value:
            problems.append(f"Value {name} changed from {old_value} to {new_value}")

    return problems


def warn_if_stale():  # Show warning if index is stale
    problems = find_problems()
    if not problems:
        return True

    print()
    #print("!" * 60)
    print("! Index does not match the current dataset")
    for problem in problems:
        print(f"!   - {problem}")
    print("! Search results will come from old data")
    #print("! Fix by running:  python build_index.py")
    #print("!" * 60)
    print()
    return False


