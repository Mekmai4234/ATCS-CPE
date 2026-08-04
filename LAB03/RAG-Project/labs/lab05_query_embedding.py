


"""
Lab 5: Experiment with query embedding to vector space using 
the same model as used for chunk embeddings (Lab 3).

Compile: python labs/lab05_query_embedding.py
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.embedding_model import EmbeddingModel


def main():
    print("Lab 5: Query Embedding")

    model = EmbeddingModel(config.EMBEDDING_MODEL_NAME)

    query = "ถุงยางอนามัยแตกต้องทำยังไง"
    print(f" Exp Query: {query}")

    query_vector = model.encode_query(query)
    print(f"Found query vector of size: {query_vector.shape} dimensions")
    print(f"Example of first 5 numerical values: {query_vector[:5]}")


if __name__ == "__main__":
    main()

