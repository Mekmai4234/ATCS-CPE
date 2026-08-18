


"""
text_splitter.py
-----------------
split long texts into smaller chunks to improve embedding and retrieval accuracy, as shorter texts will have more focused embeddings.
in this answer in sex_q_a.txt, most answers are short enough to be considered as a single chunk.
"""

def split_text(text, chunk_size, overlap):
    """
    Split a long text into smaller chunks of size chunk_size characters,
    with an overlap between consecutive chunks to avoid losing context.
    If the text is shorter than chunk_size, return it as a single chunk.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap  # ถอยกลับมาเล็กน้อยให้ชิ้นถัดไปเหลื่อมกัน

    return chunks


def build_chunks(qa_records, chunk_size, overlap):
    """
    Receive a list of question-answer pairs (from document_loader.load_qa_file)
    and create a list of "chunks" with metadata for storing in chunks.json

    Each chunk is a text that will be used for embedding, combining "question + answer"
    to help retrieve relevant information from both the question and the answer.
    """
    all_chunks = []

    for record in qa_records:
        full_text = f"Question: {record['question']} Answer: {record['answer']}"
        text_pieces = split_text(full_text, chunk_size, overlap)

        for part_idx, piece in enumerate(text_pieces):
            all_chunks.append({
                "chunk_id": len(all_chunks),
                "qa_id": record["id"],
                "category": record["category"],
                "question": record["question"],
                "answer": record["answer"],
                "text": piece,
                "part_idx": part_idx,
                "line_no": record["line_no"],
            })

    return all_chunks






