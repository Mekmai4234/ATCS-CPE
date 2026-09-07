# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Problem 02: Vocabulary Mismatch (Medical/Formal vs Slang) and Token order (Position)
# Uses real questions from cat_qa_dataset.txt
from data_loader import load_qa

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def bow(text):
    result = {}
    for token in text.lower().replace("?", "").replace(".", "").replace(",", "").split():
        result[token] = result.get(token, 0) + 1
    return result


def with_position(text):
    return [(i, token) for i, token in enumerate(text.split())]


def run():
    data = load_qa()
    target = next((d for d in data if "litter box" in d["question"].lower()), data[0])

    formal_q = target["question"]
    slang_q = "Why does my kitty poop outside the sand tray?"

    print(f"{CYAN}1. Slang vs Formal Vocabulary Mismatch:{RESET}")
    print("  Formal/Dataset question :", formal_q)
    print("  Slang/User question     :", slang_q)
    print("  BoW (formal)            :", bow(formal_q))
    print("  BoW (slang)             :", bow(slang_q))

    common = set(bow(formal_q)) & set(bow(slang_q))
    print(f"  Exact-token overlap     : {RED}{common or 'None'}{RESET}")
    print(f"  -> {RED}Failure:{RESET} Both ask about litter boxes, but BoW finds zero overlap (kitty != cat, sand tray != litter box).")

    print(f"\n{CYAN}2. Token Order (Position) Inversion Effect:{RESET}")
    a = "cats should not eat dog food because protein is insufficient"
    b = "dog food should not eat cats because protein is insufficient"
    print("  Sentence A :", a)
    print("  Sentence B :", b)
    print(f"  BoW Identical?  : {RED}{bow(a) == bow(b)}{RESET} (BoW cannot tell meaning was inverted!)")
    print("  Position in A   :", with_position(a)[:4])
    print("  Position in B   :", with_position(b)[:4])

    print(f"\n{YELLOW}Cause:{RESET} BoW/Keyword search cannot bridge slang differences and ignores token sequence.")
    print(f"{GREEN}Solution:{RESET} Transformers use Positional Embeddings + Self-Attention (paraphrase-multilingual-MiniLM-L12-v2)")
    print("          along with Query Normalization (SLANG_MAP) and HyDE/Multi-Query to capture semantic intent.")


if __name__ == "__main__":
    run()
