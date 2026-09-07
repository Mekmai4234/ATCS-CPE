# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Problem 07: Retrieval is correct, but Generated Answer distorts critical medical facts (Faithfulness)
# Uses real answer on male cat urinary tract obstruction
from data_loader import load_qa

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def find_entry(data):
    return next(d for d in data if "urinate" in d["question"].lower() or "urinary" in d["answer"].lower())


def bad_generator(context):
    # Simulated failure: generator dangerously alters the emergency timeframe and advice
    return context.replace("24 hours", "7 days").replace("rapidly fatal", "mild and will resolve on its own")


def grounded_generator(context, entry):
    # Strict grounded response with source citation and veterinary disclaimer
    return f"{context} [Source: QA #{entry['id']}]"


def run():
    data = load_qa()
    entry = find_entry(data)
    context = entry["answer"]

    print(f"{CYAN}Clinical Question:{RESET} {entry['question']}")
    print(f"\n{CYAN}Retrieved Ground-Truth Context (KB truth):{RESET}")
    print(" ", context[:200] + "...")

    print(f"\n1. {RED}Bad Generation (Stochastic distortion of timeframe & severity):{RESET}")
    print(f"  {RED}{bad_generator(context)[:200]}...{RESET}")
    print(f"  -> {RED}Fatal Risk:{RESET} Altered '24 hours' to '7 days' and 'rapidly fatal' to 'mild and will resolve'!")

    print(f"\n2. {GREEN}Grounded Generation (Faithful + Citation Mapping [n]):{RESET}")
    print(f"  {GREEN}{grounded_generator(context, entry)[:200]}...{RESET}")
    print(f"  -> {GREEN}Verified:{RESET} 100% lexical fidelity + explicit provenance tag [Source: QA #{entry['id']}].")

    print(f"\n{YELLOW}Cause:{RESET} LLM hallucinates or alters numbers/adjectives, which in a medical domain can be fatal.")
    print(f"{GREEN}Solution:{RESET} Low temperature (T=0.2), Grounded System Prompts, Medical Disclaimer, and Word-overlap evaluation.")


if __name__ == "__main__":
    run()
