


"""
Load data from sex_q_a.txt and convert it into a list of dictionaries.
The original file format is:
    หมวด: category_name]
    Q: question_text
    A: answer_text
    (blank line separates each Q&A pair)

Since the actual data is in .txt format, we use "line_no" instead of page numbers
to reference the original location, so that we can still refer to the source text.
"""

import os

def load_qa_file(file_path):
    """
    read the .txt file and split it into individual question-answer pairs

    returns a list of dictionaries, each with the following keys:
        - id: the index of the question-answer pair (starting from 0)
        - category: the category to which the pair belongs
        - question: the question text
        - answer: the answer text
        - line_no: the line number of the "Q:" in the original file (used instead of page numbers)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    records = []
    current_category = "Unspecified Category"
    pending_question = None
    pending_line_no = None

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if line.startswith("#") or line == "":
            continue  # ข้ามคอมเมนต์และบรรทัดว่าง

        if line.startswith("[หมวด"):
            # ตัวอย่าง: [หมวด: สุขภาพทางเพศและการป้องกัน]
            current_category = line.strip("[]").replace("หมวด:", "").strip()
            continue

        if line.startswith("Q:"):
            pending_question = line[len("Q:"):].strip()
            pending_line_no = line_no
            continue

        if line.startswith("A:") and pending_question is not None:
            answer = line[len("A:"):].strip()
            records.append({
                "id": len(records),
                "category": current_category,
                "question": pending_question,
                "answer": answer,
                "line_no": pending_line_no,
            })
            pending_question = None
            pending_line_no = None
            continue

    return records





