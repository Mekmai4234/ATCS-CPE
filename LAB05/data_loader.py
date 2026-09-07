# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Load and parse cat_qa_dataset.txt into records shared by problem01-09.
import os
import re

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cat_qa_dataset.txt")
_HEADER_RE = re.compile(r"\[Category:\s*(.+?)\]")


def load_qa(path=DATA_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = f.read()

    entries = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or block.startswith("#"):
            continue

        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 3:
            continue

        header = lines[0]
        m = _HEADER_RE.match(header)
        if not m:
            continue
        category = m.group(1).strip()

        q_line = next((l for l in lines if l.startswith("Q:")), None)
        a_line = next((l for l in lines if l.startswith("A:")), None)

        if not q_line or not a_line:
            continue

        question = q_line[2:].strip()
        answer = a_line[2:].strip()

        entries.append({
            "id": len(entries),
            "category": category,
            "question": question,
            "answer": answer,
            "text": f"{question} {answer}",
        })
    return entries


def categories(entries=None):
    entries = entries if entries is not None else load_qa()
    return sorted(set(e["category"] for e in entries))


if __name__ == "__main__":
    data = load_qa()
    print(f"Total Q&A count: {len(data)}")
    print("Categories:")
    for c in categories(data):
        print(f"  - {c}")
    print("\nFirst entry example:")
    print("Q:", data[0]["question"])
    print("A:", data[0]["answer"][:100] + "...")
