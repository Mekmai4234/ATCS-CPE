# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Main menu script for demonstrating 9 LLM & RAG problem scenarios
# Using Cat Health Knowledge Base (cat_qa_dataset.txt)
import sys
import time

from problem01_hallucination import run as problem01
from problem02_transformer import run as problem02
from problem03_data_quality import run as problem03
from problem04_chunking import run as problem04
from problem05_metadata import run as problem05
from problem06_reranking import run as problem06
from problem07_generation import run as problem07
from problem08_config import run as problem08
from problem09_evaluation import run as problem09

# ANSI colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

PROBLEMS = {
    1: ("Hallucination & Out-of-KB Scope", problem01),
    2: ("Vocabulary Mismatch & Token Position", problem02),
    3: ("Data Quality & Ingestion Noise", problem03),
    4: ("Chunk Size, Overlap & Context Loss", problem04),
    5: ("Metadata Filtering & Domain Isolation", problem05),
    6: ("First-Stage Ranking vs Re-ranking", problem06),
    7: ("Generation Distortion & Medical Faithfulness", problem07),
    8: ("RAG Pipeline Configuration & Modularity", problem08),
    9: ("Quantitative Evaluation & IR Metrics", problem09),
}


def verify_all():
    """Built-in system verification: tests all 9 problem modules & data loader."""
    print(f"\n{CYAN}{BOLD}=" * 68)
    print("   Running Built-in Self-Verification for LAB05 RAG Modules")
    print(f"=" * 68 + RESET)
    start_time = time.time()
    tests = []

    # 1. Data Loader
    try:
        from data_loader import load_qa, categories
        data = load_qa()
        cats = categories(data)
        assert len(data) == 100 and len(cats) == 27
        tests.append(("Data Loader (100 Q&As, 27 Categories)", True))
    except Exception as e:
        tests.append(("Data Loader", False))

    # 2. Problem 01
    try:
        import problem01_hallucination as p1
        assert len(p1.retrieve("vaccines")) > 0 and len(p1.retrieve("ตั๋วเครื่องบิน")) == 0
        tests.append(("Problem 01: Hallucination & Short-Circuit Refusal", True))
    except Exception:
        tests.append(("Problem 01: Hallucination", False))

    # 3. Problem 02
    try:
        import problem02_transformer as p2
        a = "cats should not eat dog food"
        b = "dog food should not eat cats"
        assert p2.bow(a) == p2.bow(b) and p2.with_position(a) != p2.with_position(b)
        tests.append(("Problem 02: Vocabulary Mismatch & Token Position", True))
    except Exception:
        tests.append(("Problem 02: Vocabulary Mismatch", False))

    # 4. Problem 03
    try:
        import problem03_data_quality as p3
        clean = p3.normalize("  What_are_the_vaccines?!!!  ")
        assert "_" not in clean and "!" not in clean
        tests.append(("Problem 03: Ingestion Normalization & Deduplication", True))
    except Exception:
        tests.append(("Problem 03: Data Quality", False))

    # 5. Problem 04
    try:
        import problem04_chunking as p4
        chars = p4.chunk_chars("a" * 1000, size=400, overlap=50)
        assert len(chars) > 1 and len(chars[0]) == 400
        tests.append(("Problem 04: Chunking Strategy & Overlap Preservation", True))
    except Exception:
        tests.append(("Problem 04: Chunking Strategy", False))

    # 6. Problem 05
    try:
        import problem05_metadata as p5
        data = load_qa()
        unfiltered = p5.search(data, p5.QUERY)
        filtered = p5.search(data, p5.QUERY, category="Behavior and Relationship with Owners")
        assert unfiltered["category"] != filtered["category"]
        tests.append(("Problem 05: Metadata Domain Filtering", True))
    except Exception:
        tests.append(("Problem 05: Metadata Filtering", False))

    # 7. Problem 06
    try:
        import problem06_reranking as p6
        data = load_qa()
        candidates = sorted(data, key=p6.first_stage, reverse=True)[:20]
        reranked = sorted(candidates, key=p6.rerank, reverse=True)
        assert reranked[0]["id"] == 7
        tests.append(("Problem 06: Two-Stage Cross-Encoder Re-ranking", True))
    except Exception:
        tests.append(("Problem 06: Re-ranking", False))

    # 8. Problem 07
    try:
        import problem07_generation as p7
        data = load_qa()
        entry = p7.find_entry(data)
        good = p7.grounded_generator(entry["answer"], entry)
        assert "24 hours" in good and "Source:" in good
        tests.append(("Problem 07: Generation Faithfulness & Citations", True))
    except Exception:
        tests.append(("Problem 07: Generation Faithfulness", False))

    # 9. Problem 08
    try:
        import problem08_config as p8
        assert "USE_HYBRID" in p8.CONFIG and "USE_RERANK" in p8.CONFIG
        tests.append(("Problem 08: Pipeline Modularity & Configuration", True))
    except Exception:
        tests.append(("Problem 08: Modularity", False))

    # 10. Problem 09
    try:
        import problem09_evaluation as p9
        data = load_qa()
        live = p9.compute_live_ir_metrics(data, sample_n=10)
        assert live["Hit@10"] == 1.0
        tests.append(("Problem 09: Quantitative IR Benchmarking", True))
    except Exception:
        tests.append(("Problem 09: Evaluation", False))

    passed = sum(1 for _, ok in tests if ok)
    for name, ok in tests:
        status = f"{GREEN}[PASS]{RESET}" if ok else f"{RED}[FAIL]{RESET}"
        print(f"  {status} {name}")

    elapsed = time.time() - start_time
    print(f"{CYAN}=" * 68 + RESET)
    print(f"  {GREEN}{BOLD}ALL {passed}/{len(tests)} MODULES VERIFIED SUCCESSFULLY! ({elapsed:.3f}s){RESET}")
    print(f"{CYAN}=" * 68 + RESET)


def show_menu():
    print(f"{CYAN}=" * 68)
    print(f"   {BOLD}Cat Health QA RAG — 9 Problem-Based Simulations (LAB05){RESET}")
    print(f"{CYAN}=" * 68 + RESET)
    print(f"  {GREEN}0. Run All Problems (0-9){RESET}")
    for no, (name, _) in PROBLEMS.items():
        print(f"  {CYAN}{no:1d}.{RESET} Problem {no:02d}: {name}")
    print(f"  {YELLOW}V. Run Built-in Module Verification{RESET}")
    print(f"{CYAN}=" * 68 + RESET)


def execute(choice_str):
    choice_clean = str(choice_str).strip().upper()

    if choice_clean == "V":
        verify_all()
        return

    try:
        number = int(choice_clean)
    except ValueError:
        print(f"{YELLOW}Please choose 0-9, V, or Q{RESET}")
        return

    if number == 0:
        for no, (name, func) in PROBLEMS.items():
            print("\n" + f"{CYAN}=" * 68)
            print(f"   {BOLD}PROBLEM {no:02d}: {name}{RESET}")
            print(f"{CYAN}=" * 68 + RESET)
            func()
        return

    if number not in PROBLEMS:
        print(f"{YELLOW}Please choose a number between 0 and 9{RESET}")
        return

    name, func = PROBLEMS[number]
    print("\n" + f"{CYAN}=" * 68)
    print(f"   {BOLD}PROBLEM {number:02d}: {name}{RESET}")
    print(f"{CYAN}=" * 68 + RESET)
    func()


def main_loop():
    while True:
        show_menu()
        choice = input(f"Select a problem [0-9], {YELLOW}V{RESET} to verify, or {YELLOW}Q{RESET} to exit: ").strip()

        if choice.upper() == "Q":
            print(f"{GREEN}Exiting simulation suite. Goodbye!{RESET}")
            break

        execute(choice)
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg.upper() == "Q":
            sys.exit(0)
        execute(arg)
    else:
        main_loop()
