# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Problem 03: Duplicate / Noise / Broken Text / Normalization
# Simulates scraping/OCR noise on real questions from cat_qa_dataset.txt
import re
from data_loader import load_qa

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def make_noisy_samples(data, n=2):
    base = [d["question"] for d in data[:n]]
    raw = []
    for q in base:
        raw.append(q)                                        # original
        raw.append(q)                                        # exact duplicate
        raw.append("   " + q + "   ")                        # extra whitespace
        raw.append(q.replace(" ", "_") + "!!!")              # symbol noise
    raw.append("")                                           # empty row
    return raw


def normalize(text):
    text = text.lower()
    text = re.sub(r"[_@!\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def run():
    data = load_qa()
    raw = make_noisy_samples(data)

    print(f"{CYAN}1. Raw Ingestion Samples Before Cleaning (Simulated OCR/Scraping Noise):{RESET}")
    for x in raw:
        print(f"  {RED}{repr(x)}{RESET}")

    normalized = [normalize(x) for x in raw if x.strip()]
    unique = list(dict.fromkeys(normalized))

    print(f"\n{CYAN}2. After Normalization + Deduplication Pipeline:{RESET}")
    for x in unique:
        print(f"  {GREEN}{repr(x)}{RESET}")

    print(f"\n  Vector reduction: {RED}{len(raw)} raw samples{RESET} -> {GREEN}{len(unique)} clean vectors{RESET}")

    all_q = [normalize(d["question"]) for d in data]
    dup_count = len(all_q) - len(set(all_q))
    print(f"  Corpus Validation: Checked full cat_qa_dataset.txt ({len(data)} entries): found {GREEN}{dup_count} duplicates{RESET}")

    print(f"\n{YELLOW}Cause:{RESET} Duplicates add redundant index vectors; noise degrades similarity score matching.")
    print(f"{GREEN}Solution:{RESET} Preprocessing pipeline in document_loader.py (strip whitespace, skip comments/empty lines).")


if __name__ == "__main__":
    run()
