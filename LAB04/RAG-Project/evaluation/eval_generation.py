


# Evaluate retrieval performance using data/golden_set.json.
#
# This script compares whether BM25 and reranking improve retrieval quality.
# It runs multiple retrieval methods on the same evaluation queries.
#
#     dense_only      Semantic retrieval only (baseline from Labs 1–7)
#     bm25_only       Keyword retrieval only
#     hybrid          BM25 + Dense retrieval with RRF
#     hybrid+rerank   Hybrid retrieval with cross-encoder reranking
#                     (only when USE_RERANK = True)
#
# How to interpret the results:
#   * Hybrid should perform best on partial queries and English abbreviations.
#   * Reranking should improve MRR and nDCG more than Hit@10 because it only
#     reorders retrieved results.
#   * Strong performance only on verbatim queries indicates exact word matching
#     rather than robust retrieval.


import json
import re

import config
from evaluation.eval_retrieval import load_golden_set
from src.hybrid_retriever import tokenize
from src.prompt_templates import format_context

# Number of items — LLM calls are slow, so set low
LIMIT = 20

# Which question variant to test (natural = realistic, used for judgement)
VARIANT = "natural"


def word_overlap(text_a, text_b):
    """
    Proportion of words in text_a that also appear in text_b (0.0 - 1.0)

    If the answer is 'copied / paraphrased' from doc, value is high
    If hallucinated, value is low
    """
    words_a = set(tokenize(text_a))
    if not words_a:
        return 0.0

    words_b = set(tokenize(text_b))
    return len(words_a & words_b) / len(words_a)


def is_refusal(answer):
    """Does this answer say 'I don't know'?"""
    phrases = ["not found", "no information", "cannot answer", "sorry, no relevant information"]
    return any(phrase in answer for phrase in phrases)


def evaluate_one_item(rag, item):
    """Evaluate 1 item, return score dict"""
    query = item["variants"].get(VARIANT, item["question"])
    result = rag.ask(query)

    answer = result["answer"].replace(config.DISCLAIMER, "").strip()
    context = format_context(result["retrieved"])

    found_ids = {chunk["chunk_id"] for chunk in result["retrieved"]}
    correct_ids = set(item["relevant_chunk_ids"])

    return {
        "id": item["id"],
        "query": query,
        "answer": answer,
        "refused": is_refusal(answer),
        "context_hit": bool(found_ids & correct_ids),   # Did it find the correct chunk?
        "has_citation": bool(re.search(r"\[\d+\]", result["answer"])),
        "faithfulness": round(word_overlap(answer, context), 4),
        "correctness": round(word_overlap(answer, item["reference_answer"]), 4),
        "relevance": round(word_overlap(query, answer), 4),
        "seconds": result["timings"]["Total"],
    }


def summarize(rows):
    """Average score across all items"""
    def mean(key):
        return round(sum(row[key] for row in rows) / len(rows), 4)

    return {
        "Total Items": len(rows),
        "Refusal Rate": mean("refused"),
        "Context Hit Rate": mean("context_hit"),
        "Has Citation [n]": mean("has_citation"),
        "faithfulness": mean("faithfulness"),
        "correctness": mean("correctness"),
        "relevance": mean("relevance"),
        "Avg Time (s)": mean("seconds"),
    }


def main():
    print("=== Answer Quality Evaluation ===")

    from src.rag_pipeline import RAGPipeline

    items = load_golden_set()["items"][:LIMIT]

    # Disable memory because each item must be independent
    original_memory = config.USE_MEMORY
    config.USE_MEMORY = False

    rag = RAGPipeline()
    rag.show_settings()

    if not config.USE_LLM:
        print("\n! USE_LLM = False — Answer is just extracted text, not generated")
        print("  Set USE_LLM = True in config.py for meaningful numbers")

    rows = []
    for number, item in enumerate(items, start=1):
        print(f"  [{number}/{len(items)}] {item['id']}", end="\r", flush=True)
        rows.append(evaluate_one_item(rag, item))

    config.USE_MEMORY = original_memory     # Restore original setting

    summary = summarize(rows)

    print("\n\n=== Summary ===")
    for name, value in summary.items():
        print(f"  {name:26s} {value}")

    print("\n=== Least faithful answers (suspected hallucinations) ===")
    for row in sorted(rows, key=lambda r: r["faithfulness"])[:3]:
        print(f"  {row['id']} ({row['faithfulness']:.3f}) {row['query'][:50]}")
        print(f"      {row['answer'][:100]}...")

    with open(config.EVAL_GENERATION_FILE, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": rows}, f, ensure_ascii=False, indent=2)
    print(f"\nSaved report at {config.EVAL_GENERATION_FILE}")


if __name__ == "__main__":
    main()
