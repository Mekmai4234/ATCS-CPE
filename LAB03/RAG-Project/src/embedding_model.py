


"""
wrap sentence-transformers for easier usage
model that converts text into embeddings, where semantically similar texts will have embeddings that are 
"close" to each other in a high-dimensional space

"""

from sentence_transformers import SentenceTransformer

class EmbeddingModel:
    def __init__(self, model_name):
        print(f"[embedding_model] Loading model: {model_name} ...")
        self.model = SentenceTransformer(model_name)
        print("[embedding_model] Model loaded successfully.")

    def encode(self, texts):
        """
        Convert a list of texts into a numpy array of embeddings
        The shape of the returned array is (texts number, embeddings dimension)
        """
        return self.model.encode(
            texts,
            show_progress_bar=True,
            normalize_embeddings=True,  # normalize ไว้ล่วงหน้า เพื่อให้ค้นด้วย cosine similarity ง่ายขึ้น
        )

    def encode_query(self, query_text):
        """Convert a single query into a vector"""
        return self.model.encode([query_text], normalize_embeddings=True)[0]
