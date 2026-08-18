



# Create data/golden_set.json from the existing chunk store.
#
# Each chunk comes from a real Q&A pair, so the correct target chunk is already known.
# This provides automatic ground truth without writing every test item manually.
#
# Original questions are too easy because BM25 can match the same words directly.
# To create more realistic tests, each question is converted into four query types:
#
# verbatim  Original question for checking the system's upper limit.
# slang     Medical terms rewritten in everyday language.
# partial   Short keyword-style query.
# natural   Natural user-style question for realistic evaluation.
#
# The gap between verbatim and natural results shows how well the system handles
# real user queries.
#
# Set the number of items with config.GOLDEN_SET_SIZE.
# Run: python -m evaluation.build_golden_set



import json
import random
import re

import config

# Opposite of SLANG_MAP in query_transform: medical term -> colloquial term
TO_SLANG = {
    "cat": "kitty",
    "cat owner": "cat slave",
    "dry food": "kibble",
    "feces": "poop",
    "urine": "pee",
    "veterinarian": "vet",
    "animal hospital": "clinic",
}

PREFIXES = ["I want to know ", "Can I ask ", "I am wondering ", ""]
SUFFIXES = [" please", " thanks", ""]
SEED = 42        # Lock random seed so we get the same exam set every time

STOPWORDS = {"is", "what", "that", "and", "or", "of", "in", "has", "some",
             "can", "how", "the", "a", "an", "are", "to", "for"}


def make_variants(question, rng):
    """Generate 4 variants from 1 original question"""
    variants = {"verbatim": question}

    # slang: Replace medical terms with colloquial terms
    slang = question
    for formal, casual in TO_SLANG.items():
        # Use regex with word boundaries to avoid matching substrings like "cat" in "indicate"
        slang = re.sub(r'\b' + re.escape(formal) + r'\b', casual, slang, flags=re.IGNORECASE)
    if slang != question:
        variants["slang"] = slang

    # partial: Remove stopwords, keep content words
    words = [w for w in re.split(r"[\s()/]+", re.sub(r"\(.*?\)", "", question))
             if w and w not in STOPWORDS and len(w) > 1]
    if len(words) >= 2:
        variants["partial"] = " ".join(words[:max(2, int(len(words) * 0.6))])

    # natural: Add conversational prefix/suffix
    core = re.sub(r"^(what is|how to)\s*", "", question, flags=re.IGNORECASE).strip()
    variants["natural"] = f"{rng.choice(PREFIXES)}{core}{rng.choice(SUFFIXES)}".strip()

    return variants


def main():
    print("=== Build Golden Set ===")
    with open(config.CHUNK_STORE_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    # All chunks from the same qa_id are considered correct
    # (Long answer split into 3 chunks, finding any is correct)
    by_qa = {}
    for chunk in chunks:
        by_qa.setdefault(chunk["qa_id"], []).append(chunk["chunk_id"])

    # Use only part_idx == 0 because it contains the full question
    primary = [c for c in chunks if c.get("part_idx", 0) == 0]

    # Randomize across categories to prevent large categories from dominating
    rng = random.Random(SEED)
    by_category = {}
    for chunk in primary:
        by_category.setdefault(chunk["category"], []).append(chunk)

    selected = []
    per_category = max(1, config.GOLDEN_SET_SIZE // len(by_category))
    for pool in by_category.values():
        rng.shuffle(pool)
        selected.extend(pool[:per_category])
    selected = sorted(selected, key=lambda c: c["chunk_id"])[:config.GOLDEN_SET_SIZE]

    items = [
        {
            "id": f"g{c['qa_id']:04d}",
            "category": c["category"],
            "question": c["question"],
            "variants": make_variants(c["question"], rng),
            "relevant_chunk_ids": sorted(by_qa[c["qa_id"]]),
            "reference_answer": c["answer"],
        }
        for c in selected
    ]

    with open(config.GOLDEN_SET_FILE, "w", encoding="utf-8") as f:
        json.dump({"size": len(items), "items": items}, f, ensure_ascii=False, indent=2)

    print(f"Created {len(items)} items from {len(chunks)} chunks")
    print("\nExample:")
    for name, text in items[0]["variants"].items():
        print(f"  {name:9s}: {text}")
    print(f"  Should find: {items[0]['relevant_chunk_ids']}")
    print(f"\nSaved at {config.GOLDEN_SET_FILE}")


if __name__ == "__main__":
    main()
