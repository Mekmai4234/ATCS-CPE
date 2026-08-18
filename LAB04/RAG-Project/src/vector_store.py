

# Store and search embedding vectors using FAISS.
# IndexFlatIP uses inner product to compare normalized vectors.
# With normalized embeddings, inner product is equal to cosine similarity.
# Higher scores indicate more similar vectors.


import json

import faiss
import numpy as np


class VectorStore:
    def __init__(self):
        self.index = None

    def build(self, embeddings):
        """Build new index from all vectors (2D numpy array)"""
        embeddings = np.asarray(embeddings, dtype="float32")
        n_vectors, n_dimensions = embeddings.shape

        self.index = faiss.IndexFlatIP(n_dimensions)
        self.index.add(embeddings)
        return self

    def save(self, path):
        faiss.write_index(self.index, path)
        print(f"[vector_store] Saved index at {path}")

    def load(self, path):
        self.index = faiss.read_index(path)
        return self

    def search(self, query_vector, top_k):
# Find the top_k vectors most similar to the query vector.
# Returns a list of (index, score) pairs sorted by similarity.
# The index maps directly to the corresponding chunk in chunk_store.


        # FAISS always expects 2D, so wrap [] to make it 1 row
        query_vector = np.asarray([query_vector], dtype="float32")
        scores, positions = self.index.search(query_vector, top_k)

        results = []
        for position, score in zip(positions[0], scores[0]):
            if position != -1:      # -1 = FAISS didn't find (happens when index is smaller than top_k)
                results.append((int(position), float(score)))
        return results


def save_chunk_store(chunks, path):
    """Save all chunk contents — order must match index exactly"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"[vector_store] Saved chunk store at {path}")


def load_chunk_store(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
