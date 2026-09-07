# -*- coding: utf-8 -*-
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
# Problem 01: Hallucination / No evidence in Retrieved Context
# Uses cat_qa_dataset.txt as a real Knowledge Base
from data_loader import load_qa

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

DOCS = load_qa()


def retrieve(question, top_k=3):
    words = [w.lower() for w in question.replace("?", "").split() if len(w) > 2]
    scored = [(sum(w in d["text"].lower() for w in words), d) for d in DOCS]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:top_k]]


def bad_generate(question, context):
    if not context:
        # Simulated failure: model hallucinates a dangerous answer without KB evidence
        return "Giving kittens cow milk and chocolate makes them grow faster! (Fabricated answer - dangerous & not in KB)"
    return context[0]["answer"]


def grounded_generate(question, context):
    if not context:
        return "Sorry, no relevant information found in the Cat Health Knowledge Base."
    return context[0]["answer"]


def run():
    q_in_kb = "What are the essential vaccines for cats?"
    q_out_of_kb = "ตั๋วเครื่องบินไปเชียงใหม่ราคาเท่าไหร่ (Flight ticket price to Chiang Mai)"

    for label, q in [("Out of KB scope", q_out_of_kb), ("In KB scope", q_in_kb)]:
        ctx = retrieve(q)
        print(f"{CYAN}--- Query ({label}): {q}{RESET}")
        print("  Retrieved Context :", [d["question"] for d in ctx] or f"{RED}Not found in KB{RESET}")
        print(f"  {RED}Bad Generation   :{RESET} {bad_generate(q, ctx)}")
        print(f"  {GREEN}Fixed Grounded   :{RESET} {grounded_generate(q, ctx)}")
        print()

    print(f"{YELLOW}Cause:{RESET} The generator answers even though the Retrieved Context has no supporting evidence")
    print("       e.g. asking non-cat queries outside cat_qa_dataset.txt scope.")
    print(f"{GREEN}Solution:{RESET} Grounded prompt constraints + refusal when context is empty (config.NO_CONTEXT_MESSAGE).")


if __name__ == "__main__":
    run()
