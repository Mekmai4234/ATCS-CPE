# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Problem 04: Chunk too large / too small / Overlap
# Uses real content from Cat Health and Disease Prevention category
from data_loader import load_qa

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

CATEGORY = "Cat Health and Disease Prevention"


def chunk_words(words, size, overlap=0):
    step = size - overlap
    return [" ".join(words[i:i + size]) for i in range(0, len(words), step)]


def chunk_chars(text, size=400, overlap=50):
    step = size - overlap
    chunks = []
    for i in range(0, len(text), step):
        chunks.append(text[i:i + size])
    return chunks


def run():
    data = load_qa()
    docs = [d["answer"] for d in data if d["category"] == CATEGORY]
    doc = " ".join(docs)
    words = doc.split()

    print(f"{CYAN}Corpus Sample: Combined answers from '{CATEGORY}' ({len(words)} words, {len(doc)} chars){RESET}")

    print(f"\n1. {RED}Large chunk (size=200 words): [Risk: Embedding Dilution]{RESET}")
    for c in chunk_words(words, 200)[:2]:
        print("  -", c[:130] + "...")

    print(f"\n2. {RED}Small chunk (size=15 words): [Risk: Fragmented Context / Cutoff Warnings]{RESET}")
    for c in chunk_words(words, 15)[:3]:
        print("  -", c)

    print(f"\n3. {GREEN}Production Chunking: Character-based (size=400 chars, overlap=50 chars):{RESET}")
    char_chunks = chunk_chars(doc, size=400, overlap=50)
    for i, c in enumerate(char_chunks[:2], 1):
        print(f"  - Chunk {i} ({len(c)} chars): {c[:110]}...")
    print(f"  -> Preserves 50-character boundary overlap between chunks to avoid broken medical warnings.")

    print(f"\n{YELLOW}Cause:{RESET}")
    print("  - Too large: Multiple medical topics get merged, diluting vector representations.")
    print("  - Too small: Critical medical warnings (e.g. hepatic lipidosis, blockage) get severed.")
    print("  - Overlap: Ensures continuity across chunk boundaries.")
    print(f"{GREEN}Solution:{RESET} Standardized config: CHUNK_SIZE = 400 chars, CHUNK_OVERLAP = 50 chars + Concatenating Q&A.")


if __name__ == "__main__":
    run()
