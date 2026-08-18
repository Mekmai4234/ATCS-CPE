


"""
vector_store.py
----------------
Wrap FAISS usage for easier implementation of:
1) Building index from all vectors
2) Saving / loading index to/from disk
3) Searching for most similar vectors (similarity search)

beacause we normalize the vectors when creating embeddings (embedding_model.py),
using Inner Product (IndexFlatIP) is equivalent to using cosine similarity.
The higher the score = the more similar they are.

"""

import json

import faiss
import numpy as np


class VectorStore:
    def __init__(self, dimension=None):
        self.dimension = dimension
        self.index = None

    def build_index(self, embeddings):
        """ create FAISS index from all vectors (numpy array 2D) """
        embeddings = np.asarray(embeddings, dtype="float32")
        self.dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        return self.index

    def save(self, index_path):
        faiss.write_index(self.index, index_path)
        print(f"[vector_store] Saved FAISS index to: {index_path}")

    def load(self, index_path):
        self.index = faiss.read_index(index_path)
        self.dimension = self.index.d
        return self.index

    def search(self, query_vector, top_k):
        
        #Search for the most similar vectors to the query_vector
        #Return (scores, indices) where indices are the positions in the chunk_store
        
        query_vector = np.asarray([query_vector], dtype="float32")
        scores, indices = self.index.search(query_vector, top_k)
        return scores[0], indices[0]


def save_chunk_store(chunks, path):
    #Save chunks with metadata to a JSON file (to be used with FAISS index)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"[vector_store] Saved chunk store to: {path}")


def load_chunk_store(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


