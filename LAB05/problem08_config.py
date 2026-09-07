# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Problem 08: RAG Configuration & Pipeline Modularity
# Demonstrates how configuration controls active components in our Cat QA RAG system
from data_loader import load_qa

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

CONFIG = {
    "KB_SOURCE": "cat_qa_dataset.txt",
    "USE_HYBRID": True,
    "USE_RERANK": False,
    "USE_QUERY_TRANSFORM": False,
    "USE_MEMORY": True,
    "USE_LLM": True,
    "SHOW_SOURCES": True,
}


def parse_cli_toggles():
    """Allow dynamic ablation toggle via CLI args, e.g. --rerank=on --hybrid=off"""
    for arg in sys.argv[1:]:
        if "=" in arg and arg.startswith("--"):
            key, val = arg[2:].split("=", 1)
            cfg_key = f"USE_{key.upper()}"
            if cfg_key in CONFIG:
                CONFIG[cfg_key] = val.lower() in ("true", "1", "on", "yes")


def run():
    parse_cli_toggles()
    data = load_qa()

    print(f"{CYAN}Active Configuration (Ablation Controller):{RESET}")
    print(f"  KB Source: {CONFIG['KB_SOURCE']} ({len(data)} Cat Q&A entries)\n")
    print(f"{CYAN}Pipeline Execution Flow:{RESET}")

    stages = [
        ("USE_MEMORY", "1. Conversation Memory", "Maintains multi-turn dialogue context", "Single-turn query only"),
        ("USE_QUERY_TRANSFORM", "2. Query Transform    ", "Multi-query / HyDE generation enabled", "Basic slang normalization only"),
        ("USE_HYBRID", "3. Hybrid Retrieval   ", "Dense FAISS + Sparse BM25 fused with RRF (k=60)", "Dense vector retrieval only"),
        ("USE_RERANK", "4. Re-ranking         ", "Cross-Encoder (BAAI/bge-reranker-v2-m3) enabled", "Top-k directly from First-Stage"),
        ("USE_LLM", "5. Answer Generation  ", "LLM grounded with Reference Data + Citations", "Fallback: return raw retrieved chunk text"),
        ("SHOW_SOURCES", "6. Source Citations   ", "Display line_no and similarity score", "Hide reference sources"),
    ]

    for key, name, on_desc, off_desc in stages:
        is_on = CONFIG.get(key, False)
        status_tag = f"{GREEN}[ ON  ]{RESET}" if is_on else f"{RED}[ OFF ]{RESET}"
        desc = on_desc if is_on else off_desc
        print(f"  {status_tag} {name} : {desc}")

    print(f"\n{YELLOW}Benefit:{RESET} Decoupled configuration enables automated Ablation Studies")
    print("         to evaluate accuracy vs latency trade-offs for each RAG component.")


if __name__ == "__main__":
    run()
