




# Central configuration for the entire project.
# Change settings here to experiment without modifying the source code.

import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

# 1. Try toggling each one and run evaluation to see how the score changes.

USE_HYBRID = True            # Search with BM25 along with dense (False = dense only)
USE_RERANK = False           # Re-rank with cross-encoder — more accurate but much slower
USE_QUERY_TRANSFORM = False  # Transform query before search — costs 1 extra LLM call per query
USE_MEMORY = True            # Remember conversation to answer follow-up questions
USE_LLM = True               # False = show raw search results, do not call LLM
SHOW_SOURCES =  False        # True = show list of references at the end of the answer
SHOW_DEBUG = False           # True = show scores and timing of each step


# 2. File Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
VECTOR_DB_DIR = os.path.join(BASE_DIR, "vector_db")


# clack python build_index.py
SOURCE_FILE = os.path.join(DATA_DIR, "cat_qa_dataset.txt")
GOLDEN_SET_FILE = os.path.join(DATA_DIR, "golden_set.json")

# Intermediate results from build_index.py
EXTRACTED_TEXT_FILE = os.path.join(OUTPUT_DIR, "extracted_text.json")
CHUNKS_FILE = os.path.join(OUTPUT_DIR, "chunks.json")
EMBEDDINGS_FILE = os.path.join(OUTPUT_DIR, "embeddings.npy")
RETRIEVAL_RESULTS_FILE = os.path.join(OUTPUT_DIR, "retrieval_results.json")
EVAL_RETRIEVAL_FILE = os.path.join(OUTPUT_DIR, "eval_retrieval.json")
EVAL_GENERATION_FILE = os.path.join(OUTPUT_DIR, "eval_generation.json")

# The actual database used by the system for searching
FAISS_INDEX_FILE = os.path.join(VECTOR_DB_DIR, "document.index")
CHUNK_STORE_FILE = os.path.join(VECTOR_DB_DIR, "chunk_store.json")
BM25_INDEX_FILE = os.path.join(VECTOR_DB_DIR, "bm25_index.pkl")
INDEX_META_FILE = os.path.join(VECTOR_DB_DIR, "index_meta.json")

# 3. Data Preparation (If edited, you must run build_index.py again)
CHUNK_SIZE = 400        # Characters per chunk (most answers are shorter than this anyway)
CHUNK_OVERLAP = 50      # Overlap adjacent chunks to prevent loss of context

# The actual model is downloaded and stored at C:\Users\----\.cache\huggingface
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# 4. Search
TOP_K = 3               # How many chunks to send to the LLM to write the answer
CANDIDATE_K = 20        # Number of candidates to retrieve before reranking
RRF_K = 60              # Constant for the RRF formula

RERANK_MODEL_NAME = "BAAI/bge-reranker-v2-m3"   # Used when USE_RERANK = True

QUERY_TRANSFORM_MODE = "multi_query"   # rewrite | multi_query | hyde
MULTI_QUERY_COUNT = 3

# 5. LLM
LLM_PROVIDER = "ollama"
LLM_MODEL = ""          # Leave empty = use default value
LLM_TEMPERATURE = 0.2   # Like a threshold value
LLM_MAX_TOKENS = 800

LLM_PROVIDERS = {
    "ollama": ("http://localhost:11434/v1", "llama3.1:8b", None),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/",
               "gemini-1.5-flash", "GOOGLE_API_KEY"),
}


# 6. Messages and Evaluation
MEMORY_MAX_TURNS = 6    # Number of conversation turns to remember
NO_CONTEXT_MESSAGE = "Sorry, no relevant information found."
DISCLAIMER = "Disclaimer: This information is for educational purposes only."

EVAL_K_VALUES = [1, 3, 5, 10]
GOLDEN_SET_SIZE = 60


# create output directories if they don't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(VECTOR_DB_DIR, exist_ok=True)
