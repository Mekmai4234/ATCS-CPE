


"""
Lab 7: Include all steps (embed query -> search in FAISS -> retrieve answer) 
into a single pipeline using the Retriever class from src/retriever.py.

test with multiple queries and save the results to outputs/retrieval_results.json

Compile: python labs/lab07_complete_retrieval.py
"""

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.retriever import Retriever

# Questions for testing the retrieval system 
# (covering multiple categories in the data) 
SAMPLE_QUERIES = [
    "ถุงยางอนามัยแตกต้องทำยังไง",
    "PrEP กับ PEP ต่างกันยังไง",
    "ควรตรวจโรคติดต่อทางเพศสัมพันธ์บ่อยแค่ไหน",
    "ความยินยอมในเรื่องเพศคืออะไร",
]

def main():
    print("Lab 7: Complete retrieval pipeline")

    retriever = Retriever(
        model_name=config.EMBEDDING_MODEL_NAME,
        index_path=config.FAISS_INDEX_FILE,
        chunk_store_path=config.CHUNK_STORE_FILE,
    )

    all_results = []

    for query in SAMPLE_QUERIES:
        print(f"\nQuery: {query}")
        results = retriever.retrieve(query, top_k=config.TOP_K)

        for rank, item in enumerate(results, start=1):
            print(f"  [{rank}] ({item['score']:.4f}) {item['question']}")

        all_results.append({
            "query": query,
            "results": results,
        })

    with open(config.RETRIEVAL_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\nSaved all results to: {config.RETRIEVAL_RESULTS_FILE}")


if __name__ == "__main__":
    main()


