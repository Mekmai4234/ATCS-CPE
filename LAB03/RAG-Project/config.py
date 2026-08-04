

"""
Project configuration.

Shared paths and constants used by all labs.
Avoid repeating hard-coded values.
"""

import os
import sys

# solve the problem of Windows console not showing Thai text (UnicodeEncodeError)
# configure stdout/stderr to use UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")

# main folder of the project
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Folder structure:
# RAG-Project/
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
VECTOR_DB_DIR = os.path.join(BASE_DIR, "vector_db")

# Data file of the knowledge base
SOURCE_FILE = os.path.join(DATA_DIR, "sex_q_a.txt")

# results intermediate files (outputs/)
EXTRACTED_TEXT_FILE = os.path.join(OUTPUT_DIR, "extracted_text.json")
CHUNKS_FILE = os.path.join(OUTPUT_DIR, "chunks.json")
EMBEDDINGS_FILE = os.path.join(OUTPUT_DIR, "embeddings.npy")
RETRIEVAL_RESULTS_FILE = os.path.join(OUTPUT_DIR, "retrieval_results.json")

#file paths for vector database (vector_db/)
FAISS_INDEX_FILE = os.path.join(VECTOR_DB_DIR, "document.index")
CHUNK_STORE_FILE = os.path.join(VECTOR_DB_DIR, "chunk_store.json")

# settings for chunking and embedding
#data is already in Q&A format, but if the answer is too long, 
# it will be split into chunks of this size (number of characters)
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50

# setting for the embedding model
#multilingual model for TH language support
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# RAG setting for the retrieval process
TOP_K = 3

# create output folders in advance if they don't exist
for _dir in (OUTPUT_DIR, VECTOR_DB_DIR):
    os.makedirs(_dir, exist_ok=True)
