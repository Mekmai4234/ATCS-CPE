


# document_loader.py
# Load data/sex_q_a.txt and convert it into a list of Q&A records.
# Each record includes the source line number for reference.


import os


def load_qa_file(file_path):

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    records = []
    category = "Uncategorized"
    question = None
    question_line = None

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("[Category"):
            category = line.strip("[]").replace("Category:", "").strip()
        elif line.startswith("Q:"):
            question = line[2:].strip()
            question_line = line_no
        elif line.startswith("A:") and question:
            records.append({
                "id": len(records),
                "category": category,
                "question": question,
                "answer": line[2:].strip(),
                "line_no": question_line,
            })
            question = None

    return records


    # Returns a list of dicts with keys:
    #    id        Sequence of Q&A pair, starting from 0
    #    category  The category of this pair
    #    question  Question text
    #    answer    Answer text
    #    line_no   Line number of "Q:" in the original file

