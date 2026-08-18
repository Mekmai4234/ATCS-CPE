# query_transform.py
# Improve user queries before retrieval.
#
# Problem
# Retrieval quality depends on the user's query. Real users often write
# short or ambiguous questions, or use slang.
#
#     "I have a sore on my private part"   ← slang
#     Knowledge base: "penis"
#
#     "So what's the difference?"          ← unclear without context
#
# Since the knowledge base uses medical terms, query transformation helps
# bridge the gap between user language and stored documents.
#
# Two levels are available:
#
# Level 1 — normalize_query()
#     No AI required. Replaces slang using a lookup table.
#     Fast, free, and always enabled.
#
# Level 2 — transform()
#     Uses an LLM when config.USE_QUERY_TRANSFORM is enabled.
#
#     rewrite
#         Rewrite the query into a clearer question.
#
#     multi_query
#         Generate multiple equivalent queries and search all of them.
#
#     hyde
#         Generate a hypothetical answer and use it as the search query.
#         This works because answer-like text is often closer to the
#         correct document than the original question.

import re

import config
from src.prompt_templates import HYDE_PROMPT, MULTI_QUERY_PROMPT, REWRITE_PROMPT

# Slang replacement table — add words as needed, no code changes required
SLANG_MAP = {
    "kitty": "cat",
    "feline": "cat",
    "cat slave": "cat owner",
    "kibble": "dry food",
    "poop": "feces",
    "pee": "urine",
    "vet": "veterinarian",
    "clinic": "animal hospital",
}

# Ending words that don't help in searching
ENDING_WORDS = re.compile(r"\s*(please|thanks|thank you)\s*$")


def normalize_query(query):
    """
    Normalize query without AI — fast and free

        "My kitty is sick"  →  "My cat is sick"
    """
    text = re.sub(r"\s+", " ", query).strip()       # Remove redundant spaces

    for casual, formal in SLANG_MAP.items():
        # Use regex with word boundaries to avoid matching substrings like "cat" in "indicate"
        text = re.sub(r'\b' + re.escape(casual) + r'\b', formal, text, flags=re.IGNORECASE)

    text = ENDING_WORDS.sub("", text)
    return text.strip() or query.strip()            # If everything was stripped, use original


def clean_line(line):
    """Remove numbering, quotes, and prefixes that LLMs like to add"""
    text = line.strip()
    text = re.sub(r"^\s*(\d+[\.\)]|[-*•])\s*", "", text)    # "1. " or "- "
    text = re.sub(r"^(Question|Query)\s*[:：]\s*", "", text)
    return text.strip().strip('"').strip("'")


class QueryTransformer:
    def __init__(self, llm):
        self.llm = llm

    def ask_llm(self, prompt):
        return self.llm.chat([{"role": "user", "content": prompt}])

    def rewrite(self, query, history):
        """Let LLM rewrite the question to be clear and self-contained"""
        history_block = f"Previous conversation:\n{history}\n\n" if history else ""
        prompt = REWRITE_PROMPT.format(history=history_block, question=query)
        return [clean_line(self.ask_llm(prompt))]

    def multi_query(self, query):
        """Let LLM generate multiple questions with the same meaning"""
        prompt = MULTI_QUERY_PROMPT.format(n=config.MULTI_QUERY_COUNT, question=query)
        answer = self.ask_llm(prompt)

        queries = [normalize_query(query)]           # Keep original query as the first one
        for line in answer.splitlines():
            new_query = clean_line(line)
            if new_query and new_query not in queries:
                queries.append(new_query)

        return queries[: config.MULTI_QUERY_COUNT + 1]

    def hyde(self, query):
        """Let LLM write a hypothetical answer and use it as a search query"""
        fake_answer = self.ask_llm(HYDE_PROMPT.format(question=query)).strip()

        # Keep original query in case the hypothetical answer is off-topic
        return [normalize_query(query), fake_answer]

    def transform(self, query, history=""):
        """
        Return list of queries for searching — always at least 1

        If LLM fails, return original query so searching doesn't break
        """
        if not config.USE_QUERY_TRANSFORM:
            return [normalize_query(query)]

        try:
            if config.QUERY_TRANSFORM_MODE == "rewrite":
                return self.rewrite(query, history)
            if config.QUERY_TRANSFORM_MODE == "hyde":
                return self.hyde(query)
            return self.multi_query(query)

        except Exception as error:
            print(f"[query_transform] Failed ({error}) — using original query")
            return [normalize_query(query)]


