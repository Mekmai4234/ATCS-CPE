

# prompt_templates.py
# Store all prompt templates in one place.
# Makes prompts easier to manage, compare, and update.
# Answers must be based only on the retrieved context.
# Inline citations are required for traceable and verifiable responses.


import config

SYSTEM_PROMPT = """You are an assistant providing health and education information. Answer based ONLY on the provided "Reference Data".

Rules:
1. Use ONLY information from "Reference Data". Do not add outside knowledge.
2. If the information is insufficient, reply with "{no_context}". Do not guess.
3. Cite the source number as [1] [2] at the end of the sentence where the information is used.
4. Use polite, straightforward, non-judgmental language.
5. If the symptoms are severe or an emergency, recommend seeing a doctor immediately.
6. Keep the answer concise, no more than 5-6 sentences."""

USER_PROMPT = """{history}Reference Data:
{context}

User's Question: {question}

Answer using ONLY the reference data above, with citations [n]"""


def format_context(chunks, max_chars=6000):
    """
    Format chunks into a numbered reference block.

    max_chars prevents the prompt from exceeding the context window — chunks are ordered by relevance.
    Truncating at the end removes the least relevant pieces.
    """
    blocks, used = [], 0
    for i, chunk in enumerate(chunks, start=1):
        block = f"[{i}] {chunk.get('answer') or chunk.get('text', '')}"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def build_messages(question, chunks, history=""):
    """Assemble a messages list to send to the LLM"""
    history_block = f"Previous conversation:\n{history}\n\n" if history else ""
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(no_context=config.NO_CONTEXT_MESSAGE)},
        {
            "role": "user",
            "content": USER_PROMPT.format(
                history=history_block,
                context=format_context(chunks),
                question=question,
            ),
        },
    ]


# --------------------------------------------------- query transform
REWRITE_PROMPT = """Rewrite the question to be clear and suitable for searching the health database.
- Correct misspellings, replace slang with medical/formal terms.
- If it is a follow-up question, fill in the context from the previous conversation so it is self-contained.
- Output as a single line search query, do not explain.

{history}Original Question: {question}

Rewritten Query:"""

MULTI_QUERY_PROMPT = """Generate {n} different versions of the question with the same meaning for broader search.
- Use different words, both conversational and medical/formal terms.
- The meaning must match the original question.
- Output 1 question per line, do not number them.

Original Question: {question}

Generated Queries:"""

HYDE_PROMPT = """Write a "hypothetical answer" for this question, in the style of a health education article.
- Length: 3-5 sentences. Use specific terms that would likely be in a real document.
- Do not worry about factual accuracy, this is only used as a proxy for searching.

Question: {question}

Hypothetical Answer:"""


# ------------------------------------------- LLM judge (ตอน evaluate)
JUDGE_PROMPT = """Evaluate the "Answer" according to the {criteria}, score 1-5
(5 = Excellent, 3 = Fair, 1 = Poor)

{reference}
Question: {question}

Answer:
{answer}

Reply in JSON ONLY: {{"score": <1-5>, "reason": "<short_reason>"}}"""
