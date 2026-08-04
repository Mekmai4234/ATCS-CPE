

"""
Main RAG program.

Answer questions using only the `sex_q_a.txt` knowledge base (retrieval-based QA).

Before running, complete **Lab 01 - Lab 04** to build the vector database:
- `vector_db/document.index`
- `vector_db/chunk_store.json`

compile: python main.py
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from src.retriever import Retriever

#DISCLAIMER = (
#    "For education only. Consult a doctor for medical advice."
#)

def print_answer(rank, item):
    print(f"\nResult {rank} (Score: {item['score']:.2f})")
    #print(f"Category: {item['category']}")
    #print(f"Similar Question: {item['question']}")
    print(f"Answer: {item['answer']}")


def main():
    if not os.path.exists(config.FAISS_INDEX_FILE):
      #  print("Vector database not found.")
      #  print("Please run lab01_extract_text.py -> lab04_create_vector_db.py first.")
        return

    print("-RAG System for Sexual Health & Education QA ---")
    print("-Enter ('exit', 'quit', or 'q' to quit)---\n")


    retriever = Retriever(
        model_name=config.EMBEDDING_MODEL_NAME,
        index_path=config.FAISS_INDEX_FILE,
        chunk_store_path=config.CHUNK_STORE_FILE,
    )

    while True:
        query = input("\nHi Bro! 😎\nAsk me anything: ").strip()

        if query.lower() in ("exit", "quit", "q"):
            print("---- ขอบใจหลายๆ เด้อ !!! ------.")
            break

        if not query:
            continue

        #results = retriever.retrieve(query, top_k=config.TOP_K)
        results = retriever.retrieve(query, top_k=1)

        if not results:
            print("No relevant answer found in the knowledge base.")
            continue

        for rank, item in enumerate(results, start=1):
            print_answer(rank, item)

      #  print(f"\n{DISCLAIMER}")


if __name__ == "__main__":
    main()




