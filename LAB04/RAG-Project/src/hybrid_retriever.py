


# Combine BM25 keyword search and dense retrieval using Reciprocal Rank Fusion (RRF).
# Hybrid retrieval improves both keyword matching and semantic search.
# Supports optional reranking for higher retrieval accuracy.
# Enable or disable features in config.py.



import os
import pickle
import re

from rank_bm25 import BM25Okapi

import config
from src.embedding_model import EmbeddingModel
from src.vector_store import VectorStore, load_chunk_store


# step 1: Word segmentation
# Thai text has no spaces between words, so split() does not work.
# Tokenize the text with PyThaiNLP before building the BM25 index.
# This enables accurate keyword matching.

THAI_PATTERN = re.compile(r"[ก-๙]+")            # Consecutive Thai characters
ENGLISH_PATTERN = re.compile(r"[A-Za-z0-9]+")   # English words or numbers


def tokenize(text):
# Tokenize text for BM25.
# Convert English words to lowercase for case-insensitive matching.
# Example: "PrEP กับ PEP ต่างกันยังไง" → ['prep', 'pep', 'กับ', 'ต่างกัน', 'ยังไง']

    tokens = []

    # English words / numbers — keep the whole word
    for match in ENGLISH_PATTERN.finditer(text):
        tokens.append(match.group().lower())

    # Thai words — must tokenize first
    for thai_text in THAI_PATTERN.findall(text):
        tokens.extend(tokenize_thai(thai_text))

    return tokens


def tokenize_thai(text):  # Tokenize Thai with pythainlp, fallback if not installed
    try:
        from pythainlp.tokenize import word_tokenize

        return [word for word in word_tokenize(text, engine="newmm") if word.strip()]
    except ImportError:
        # Fallback: Trigram character overlapping
        # Works but clearly worse — recommend pip install pythainlp
        return [text[i:i + 3] for i in range(max(1, len(text) - 2))]


# Step 2: BM25 
def build_bm25(chunks):
    """Build BM25 index from all chunks"""
    corpus = []
    for chunk in chunks:
        # Duplicate question twice because user types questions
        # Matching "question" is a better signal than matching "answer"
        text = f"{chunk['question']} {chunk['question']} {chunk['text']}"
        corpus.append(tokenize(text))

    print(f"[hybrid] Built BM25 index from {len(corpus)} chunks")
    return BM25Okapi(corpus)


def save_bm25(bm25):
    with open(config.BM25_INDEX_FILE, "wb") as f:
        pickle.dump(bm25, f)
    print(f"[hybrid] Saved BM25 index at {config.BM25_INDEX_FILE}")


def load_bm25(chunks):
    """Load saved index, or build if missing"""
    if os.path.exists(config.BM25_INDEX_FILE):
        with open(config.BM25_INDEX_FILE, "rb") as f:
            return pickle.load(f)

    bm25 = build_bm25(chunks)
    save_bm25(bm25)
    return bm25


# Step 3: RRF — รวมผลจากหลายวิธี
def reciprocal_rank_fusion(ranked_lists):
# Merge multiple ranked lists into a single ranking.
# Uses Reciprocal Rank Fusion (RRF) to combine retrieval results.
# Higher-ranked items receive higher scores.
# Items found by multiple methods receive a score boost.
# Example: 
# Dense=[12,5,88], 
# BM25=[5,300,12] → 5 ranks above 12.

    scores = {}
    for ranked in ranked_lists:
        for rank, position in enumerate(ranked, start=1):
            scores[position] = scores.get(position, 0.0) + 1.0 / (config.RRF_K + rank)

    # เรียงจากคะแนนมากไปน้อย
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


# Step 4: The Retriever

class HybridRetriever:
    def __init__(self, reranker=None):
        self.chunks = load_chunk_store(config.CHUNK_STORE_FILE)
        self.model = EmbeddingModel()
        self.store = VectorStore()
        self.store.load(config.FAISS_INDEX_FILE)
        self.reranker = reranker

        # Load BM25 only when enabled
        self.bm25 = load_bm25(self.chunks) if config.USE_HYBRID else None

    def dense_search(self, query, top_k):  # Search by meaning
        
        query_vector = self.model.encode_query(query)
        return self.store.search(query_vector, top_k)

    def bm25_search(self, query, top_k):  # Search by exact keyword
        if self.bm25 is None:
            return []

        # get_scores returns scores for "all chunks", must sort and slice top_k
        all_scores = self.bm25.get_scores(tokenize(query))
        best_positions = sorted(
            range(len(all_scores)),
            key=lambda i: all_scores[i],
            reverse=True,
        )[:top_k]

        return [(position, float(all_scores[position])) for position in best_positions]



# Retrieve the top_k most relevant chunks.
# extra_queries contains alternative query versions from query transformation.
# Each query is searched separately.
# The results are combined using Reciprocal Rank Fusion (RRF).

    def retrieve(self, query, top_k=config.TOP_K, extra_queries=None):

        queries = [query] + list(extra_queries or [])

        # Search all methods, store as ranked list
        ranked_lists = []
        dense_scores = {}
        bm25_scores = {}

        for one_query in queries:
            dense_hits = self.dense_search(one_query, config.CANDIDATE_K)
            ranked_lists.append([position for position, _ in dense_hits])
            dense_scores.update(dense_hits)

            if config.USE_HYBRID:
                bm25_hits = self.bm25_search(one_query, config.CANDIDATE_K)
                ranked_lists.append([position for position, _ in bm25_hits])
                bm25_scores.update(bm25_hits)

        # Combine ranks with RRF
        fused = reciprocal_rank_fusion(ranked_lists)

        # If reranking, pass more candidates than top_k
        keep = config.CANDIDATE_K if self.reranker else top_k

        # Map positions back to content
        results = []
        for position, score in fused[:keep]:
            chunk = dict(self.chunks[position])
            chunk["score"] = score
            chunk["dense_score"] = dense_scores.get(position)
            chunk["bm25_score"] = bm25_scores.get(position)
            results.append(chunk)

        # Re-rank
        if self.reranker:
            results = self.reranker.rerank(query, results, top_k)

        return results[:top_k]



# Display dense and BM25 retrieval results before fusion.
# Useful for debugging and comparing retrieval methods.
# Enable only when needed.

    def explain(self, query, top_k=5):

        def describe(hits):
            return [
                (position, round(score, 4), self.chunks[position]["question"][:55])
                for position, score in hits
            ]

        fused = self.retrieve(query, top_k)
        return {
            "dense": describe(self.dense_search(query, top_k)),
            "bm25": describe(self.bm25_search(query, top_k)),
            "fused": [
                (c["chunk_id"], round(c["score"], 5), c["question"][:55]) for c in fused
            ],
        }


