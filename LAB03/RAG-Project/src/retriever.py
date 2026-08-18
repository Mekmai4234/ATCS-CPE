


"""
include both steps "convert query to vector" + "search in FAISS" into a single class 
to make it easy for main.py and lab07 to use with a single function call.
"""

from src.embedding_model import EmbeddingModel
from src.vector_store import VectorStore, load_chunk_store


class Retriever:
    def __init__(self, model_name, index_path, chunk_store_path):
        self.embedding_model = EmbeddingModel(model_name)

        self.vector_store = VectorStore()
        self.vector_store.load(index_path)

        self.chunks = load_chunk_store(chunk_store_path)

    def retrieve(self, query, top_k=3):
        """
        receive a user query and return the top_k most relevant chunks
        each result is a dict containing the original chunk + its similarity score
        """
        query_vector = self.embedding_model.encode_query(query)
        scores, indices = self.vector_store.search(query_vector, top_k)

        results = []
        for score, idx in zip(scores, indices):
            if idx == -1:
                continue
            chunk = dict(self.chunks[idx])
            chunk["score"] = float(score)
            results.append(chunk)

        return results
