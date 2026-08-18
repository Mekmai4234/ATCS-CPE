

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
#
# Run: python -m evaluation.eval_retrieval

import json
import os
import time

import config
from evaluation.metrics import average, evaluate_one, print_table

# Number of items to test (None = all) — reduce for speed
LIMIT = None

# Question variants to test
VARIANTS = ["verbatim", "slang", "partial", "natural"]


def load_golden_set():
    if not os.path.exists(config.GOLDEN_SET_FILE):
        print(f"Not found {config.GOLDEN_SET_FILE}")
        print("Build first with:  python -m evaluation.build_golden_set")
        raise SystemExit(1)

    with open(config.GOLDEN_SET_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def run_one_setting(retriever, items, top_k, use_bm25, use_dense):
    """
    Run one search setting for all items and variants

    Return dict {variant: avg_score} and list of misses
    """
    config.USE_HYBRID = use_bm25        # Toggle switch directly
    retriever.bm25 = retriever.bm25 if use_bm25 else None

    scores_by_variant = {variant: [] for variant in VARIANTS}
    misses = []

    for item in items:
        for variant in VARIANTS:
            query = item["variants"].get(variant)
            if not query:
                continue

            if not use_dense:
                # bm25_only — Call BM25 directly, skip RRF
                hits = retriever.bm25_search(query, top_k)
                found = [retriever.chunks[position]["chunk_id"] for position, _ in hits]
            else:
                chunks = retriever.retrieve(query, top_k=top_k)
                found = [chunk["chunk_id"] for chunk in chunks]

            scores = evaluate_one(found, item["relevant_chunk_ids"], config.EVAL_K_VALUES)
            scores_by_variant[variant].append(scores)

            if variant == "natural" and scores[f"hit@{top_k}"] == 0:
                misses.append((item["id"], query, item["relevant_chunk_ids"], found[:5]))

    return scores_by_variant, misses


def main():
    print("=== Retrieval Quality Evaluation ===")

    golden = load_golden_set()
    items = golden["items"][:LIMIT] if LIMIT else golden["items"]
    top_k = max(config.EVAL_K_VALUES)
    print(f"Items: {len(items)} | Variants: {', '.join(VARIANTS)}\n")

    from src.hybrid_retriever import HybridRetriever, load_bm25
    from src.rerankers import get_reranker

    # Remember original setting, force enable BM25 to preload index
    original_hybrid = config.USE_HYBRID
    config.USE_HYBRID = True

    # Create retriever once, since model loading is the slowest part
    retriever = HybridRetriever()
    bm25_index = retriever.bm25

    # (name, use BM25?, use dense?, use rerank?)
    settings = [
        ("dense_only", False, True, False),
        ("bm25_only", True, False, False),
        ("hybrid", True, True, False),
    ]
    if config.USE_RERANK:
        settings.append(("hybrid+rerank", True, True, True))

    reranker = get_reranker()
    results = {}
    all_misses = []

    for name, use_bm25, use_dense, use_rerank in settings:
        start_time = time.time()

        retriever.bm25 = bm25_index if use_bm25 else None
        retriever.reranker = reranker if use_rerank else None

        scores_by_variant, misses = run_one_setting(
            retriever, items, top_k, use_bm25, use_dense
        )

        all_scores = [s for scores in scores_by_variant.values() for s in scores]
        results[name] = {
            "overall": average(all_scores),
            "by_variant": {v: average(s) for v, s in scores_by_variant.items() if s},
            "ms_per_query": round((time.time() - start_time) * 1000 / len(all_scores), 1),
        }
        all_misses = misses

        print(f"  {name:16s} finished in {time.time() - start_time:.1f}s")

    config.USE_HYBRID = original_hybrid     # Restore original setting

    # ---------------------------------------------------------- Report
    columns = ["hit@1", f"hit@{top_k}", "mrr", "ndcg@3"]

    print("\n=== Overall (All variants) ===")
    print_table({name: r["overall"] for name, r in results.items()}, columns)

    for variant in VARIANTS:
        rows = {name: r["by_variant"].get(variant, {}) for name, r in results.items()}
        if any(rows.values()):
            print(f"\n=== Variant: {variant} ===")
            print_table(rows, columns)

    print("\n=== Speed ===")
    for name, report in results.items():
        print(f"  {name:16s} {report['ms_per_query']:8.1f} ms per query")

    baseline = results["dense_only"]["overall"]["mrr"]
    best_name = max(results, key=lambda n: results[n]["overall"]["mrr"])
    best = results[best_name]["overall"]["mrr"]
    if best_name != "dense_only" and baseline > 0:
        change = (best - baseline) / baseline * 100
        print(f"\nBest: {best_name} — MRR {best:.4f}")
        print(f"vs dense_only {baseline:.4f}  ({change:+.1f}%)")

    if all_misses:
        print(f"\n=== Examples of misses (natural variant) ===")
        for item_id, query, expected, found in all_misses[:5]:
            print(f"  {item_id}: {query[:55]}")
            print(f"      Expected {expected} | Found {found}")

    with open(config.EVAL_RETRIEVAL_FILE, "w", encoding="utf-8") as f:
        json.dump({"n_items": len(items), "results": results}, f,
                  ensure_ascii=False, indent=2)
    print(f"\nSaved report at {config.EVAL_RETRIEVAL_FILE}")


if __name__ == "__main__":
    main()
