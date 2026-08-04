

  

"""
Lab 3: Convert each chunk (outputs/chunks.json) into embeddings
using the sentence-transformers model that supports Thai language
Save the results to outputs/embeddings.npy

Compile: python labs/lab03_create_embeddings.py
"""

import json
import os
import sys

import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.embedding_model import EmbeddingModel


def main():
    print("=== Lab 3: Create Embeddings ===")
    print(f"Reading file: {config.CHUNKS_FILE}")

    with open(config.CHUNKS_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    texts = [chunk["text"] for chunk in chunks]

    model = EmbeddingModel(config.EMBEDDING_MODEL_NAME)
    embeddings = model.encode(texts)

    print(f"Found embeddings of size: {embeddings.shape}  (number of chunks, \
          number of dimensions)")

    np.save(config.EMBEDDINGS_FILE, embeddings)
    print(f"Results saved to: {config.EMBEDDINGS_FILE}")


if __name__ == "__main__":
    main()
