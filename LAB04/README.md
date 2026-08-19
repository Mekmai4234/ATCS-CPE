# DL-04-RAG System Development I

## Overview
This project implements a complete, customizable Retrieval-Augmented Generation (RAG) system. It combines document retrieval with Large Language Models (LLMs) to answer questions based on a provided dataset (`cat_qa_dataset.txt`).

The system is highly configurable via `config.py` and supports:
* **Hybrid Retrieval**: Combining dense vectors (FAISS) and sparse keyword search (BM25).
* **Reranking**: Improving search relevance using a Cross-Encoder.
* **Query Transformation**: Rewriting, expanding (Multi-Query), or HyDE to improve recall.
* **Conversation Memory**: Retaining context for follow-up questions.
* **Multiple LLM Providers**: Supports local models via Ollama, or APIs like OpenAI and Google Gemini.

---

## 🏗️ System Workflow

The workflow of the application follows a standard RAG pipeline:

1.  **Input**: The user provides a query in the terminal. If Memory is enabled, past conversation turns are appended to contextualize the query.
2.  **Retrieval**: 
    *   **Dense Search**: Embeds the query using `sentence-transformers` and searches the `FAISS` index.
    *   **Sparse Search**: Uses BM25 (if Hybrid is enabled) for exact keyword matching.
    *   **Reranking**: (Optional) Re-scores the retrieved candidates using a Cross-Encoder model.
3.  **Context**: The top-K retrieved text chunks are combined and formatted into a single context block using prompt templates.
4.  **LLM**: The formulated prompt (containing the context and user query) is sent to the configured LLM (e.g., Ollama, OpenAI, Gemini).
5.  **Output**: The LLM generates a grounded response, which is streamed or displayed back to the user in the terminal.

---

## 📂 Project Structure

```text
RAG-Project/
├── build_index.py                       # Script to build the vector and sparse indexes from data
├── config.py                            # Central project configuration settings
├── create_ppt.py                        # Script to generate a presentation
├── main.py                              # Application entry point to interact with the RAG system
├── requirements.txt                     # Required Python packages
│ 
├── data/                                # Data directory
│   ├── cat_qa_dataset.txt               # Source text dataset (Cats QA)
│   └── golden_set.json                  # Ground truth dataset for evaluation
│ 
├── evaluation/                          # Evaluation scripts and metrics
│   ├── __init__.py
│   ├── build_golden_set.py              # Script to build evaluation ground truth
│   ├── eval_generation.py               # Evaluates the LLM generation quality
│   ├── eval_retrieval.py                # Evaluates the retrieval accuracy
│   └── metrics.py                       # Defines metrics for evaluation
├── labs/                                # Step-by-step educational lab scripts
│   ├── lab01_extract_text.py            # Extract text from the source file
│   ├── lab02_chunking.py                # Split text into chunks
│   ├── lab03_create_embeddings.py       # Generate embeddings
│   ├── lab04_create_vector_db.py        # Build the FAISS vector database
│   ├── lab05_query_embedding.py         # Create query embeddings
│   ├── lab06_similarity_search.py       # Retrieve top-k relevant chunks
│   └── lab07_complete_retrieval.py      # Complete retrieval pipeline
│ 
├── outputs/                             # Intermediate outputs and logs
│   ├── chunks.json                      # Processed text chunks
│   ├── embeddings.npy                   # Numerical embeddings for chunks
│   ├── eval_generation.json             # Generation evaluation results
│   ├── eval_retrieval.json              # Retrieval evaluation results
│   ├── extracted_text.json              # Raw extracted text
│   └── retrieval_results.json           # Sample retrieval results
│ 
├── src/                                 # Core RAG system modules
│   ├── __init__.py
│   ├── document_loader.py               # Handles loading source documents
│   ├── embedding_model.py               # Manages text embedding generation
│   ├── generator.py                     # Handles context generation and LLM interaction
│   ├── hybrid_retriever.py              # Performs hybrid retrieval (dense + sparse search)
│   ├── index_meta.py                    # Utilities for index metadata management
│   ├── memory.py                        # Handles conversation history
│   ├── prompt_templates.py              # Stores templates for LLM prompts
│   ├── query_transform.py               # Modifies and transforms user queries
│   ├── rag_pipeline.py                  # Orchestrates the overall RAG workflow
│   ├── rerankers.py                     # Reranks retrieved documents
│   ├── retriever.py                     # Standard semantic retrieval logic
│   ├── text_splitter.py                 # Splits text into smaller chunks
│   └── vector_store.py                  # Interfaces with FAISS vector database
│ 
└── vector_db/                           # Stored indexes
    ├── bm25_index.pkl                   # BM25 sparse index for lexical search
    ├── chunk_store.json                 # Stores chunk texts and metadata
    ├── document.index                   # Dense vector index (FAISS)
    └── index_meta.json                  # Metadata about the vector database
```

### Important Files & Core Components
*   **`config.py`**: The control center of the project. Toggle features like `USE_HYBRID`, `USE_RERANK`, `USE_MEMORY`, or switch LLM providers here.
*   **`build_index.py`**: The ingestion pipeline. It reads `data/cat_qa_dataset.txt`, chunks it, creates embeddings, and saves the FAISS and BM25 indexes to `vector_db/`.
*   **`main.py`**: The interactive chat loop. Run this to test and interact with the RAG system.
*   **`src/rag_pipeline.py`**: Connects all individual modules (memory, query transform, retrieval, reranking, generation) into a unified pipeline.
*   **`src/generator.py`**: Manages API calls to the LLM backend (Ollama, OpenAI, or Gemini) using the standard OpenAI-compatible API interface.
*   **`src/embedding_model.py` & `src/vector_store.py`**: Handle the transformation of text into dense vectors using `sentence-transformers` and the storage/retrieval via `faiss-cpu`.

## 🛠️ Technologies Used
*   **Vector Database**: `faiss-cpu` (Facebook AI Similarity Search)
*   **Embeddings**: `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`)
*   **Sparse Retrieval**: BM25
*   **LLM Providers**: Local via Ollama, or Cloud APIs (OpenAI, Gemini)
*   **Reranking Model**: `BAAI/bge-reranker-v2-m3`

## Context Summary

This RAG (Retrieval-Augmented Generation) project is designed to act as an intelligent, conversational Q&A assistant that answers user queries based on a specific knowledge base (`cat_qa_dataset.txt`). It solves the problem of standard LLMs hallucinating or lacking domain-specific knowledge by grounding the model's responses in factual, retrieved data.

The system processes information through a precise workflow:

*   **User Input**: The user asks a question in the terminal (`main.py`). The system's memory module (`src/memory.py`) contextualizes the question using previous conversation turns, and the query transformer (`src/query_transform.py`) can optionally refine it to improve searchability.
*   **Retrieval**: The system converts the query into a dense vector via `sentence-transformers` (`src/embedding_model.py`) to perform semantic similarity search in a FAISS database (`src/vector_store.py`). If hybrid search is enabled, a BM25 sparse index (`src/hybrid_retriever.py`) simultaneously performs exact keyword matching. An optional cross-encoder (`src/rerankers.py`) then rescores the best candidates to ensure maximum relevance.
*   **Context**: The top-ranked retrieved text chunks are extracted and assembled into a structured prompt using predefined templates (`src/prompt_templates.py`).
*   **LLM**: The formulated prompt, containing both the retrieved context and the user's original question, is sent to the configured language model (Ollama, OpenAI, or Gemini via `src/generator.py`).
*   **Output**: The LLM analyzes the context and generates a final, accurate response, which is returned and displayed to the user in the terminal.

By orchestrating these components (`src/rag_pipeline.py`), the project ensures that the generated answers are highly relevant, traceable, and specifically derived from the provided dataset.
