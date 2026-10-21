"""Private JSON-lines subprocess: isolate blocking Chroma calls from the async coordinator."""

import json
import os
import sys


def main():
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ.setdefault("RAYON_NUM_THREADS", "2")
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=sys.argv[1], settings=Settings(anonymized_telemetry=False)
    )
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request["operation"]
            args = request.get("args", {})
            if operation == "has_data":
                result = any(item.count() for item in client.list_collections())
                print(json.dumps({"ok": True, "result": result}), flush=True)
                continue
            if operation == "upsert":
                collection = client.get_or_create_collection(
                    request["collection"],
                    embedding_function=None,
                    configuration={"hnsw": {"space": "cosine"}},
                )
            else:
                try:
                    collection = client.get_collection(
                        request["collection"], embedding_function=None
                    )
                except chromadb.errors.NotFoundError:
                    if operation not in {"get", "count", "delete"}:
                        raise
                    result = (
                        {"ids": []} if operation == "get" else (0 if operation == "count" else None)
                    )
                    print(json.dumps({"ok": True, "result": result}), flush=True)
                    continue
            if operation == "upsert":
                collection.upsert(**args)
                result = None
            elif operation == "query":
                result = collection.query(**args)
            elif operation == "get":
                result = collection.get(**args)
            elif operation == "delete":
                collection.delete(**args)
                result = None
            elif operation == "count":
                result = collection.count()
            else:
                raise ValueError("Unsupported operation")
            print(json.dumps({"ok": True, "result": result}), flush=True)
        except Exception:
            # Neither provider text nor transcript content is echoed in diagnostics.
            print(json.dumps({"ok": False}), flush=True)


if __name__ == "__main__":
    main()
