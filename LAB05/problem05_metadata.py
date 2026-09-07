# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Problem 05: Similarity Search returns right keywords but wrong Category/Metadata
# Uses real data from cat_qa_dataset.txt across different categories
from data_loader import load_qa

# ANSI colors for presentation
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

# Query about cat behavioral biting & scratching:
# Without metadata filtering, words 'how', 'stop', 'cat' collide with obesity weight-loss answer.
QUERY = "how to stop cat scratching and biting"


def score(query, text):
    return sum(word in text.lower() for word in query.lower().split())


def search(data, query, category=None):
    docs = data if category is None else [d for d in data if d["category"] == category]
    return max(docs, key=lambda d: score(query, d["question"] + " " + d["answer"]))


def run():
    data = load_qa()

    bad = search(data, QUERY)
    good = search(data, QUERY, category="Behavior and Relationship with Owners")

    print(f"{CYAN}Query: {QUERY}{RESET}")
    print("\n1. Without Metadata Filtering (pure keyword overlap, picks medical instead of behavioral):")
    print(f"  {RED}[{bad['category']}]{RESET} Q: {bad['question']}")

    print("\n2. With Metadata Filtering (Filter category='Behavior and Relationship with Owners'):")
    print(f"  {GREEN}[{good['category']}]{RESET} Q: {good['question']}")

    print(f"\n{YELLOW}Cause:{RESET} Vector/Keyword similarity selects the most word overlaps regardless of domain context.")
    print(f"{GREEN}Solution:{RESET} Store rich metadata (category, qa_id, line_no) in chunk_store.json to enable post-filtering.")


if __name__ == "__main__":
    run()
