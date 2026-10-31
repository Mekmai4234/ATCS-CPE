"""Conservative duplicate checks; semantic accuracy still requires reviewed evidence."""

import unicodedata

from .models import error


def validate_learning_items(kind, items):
    if kind == "study_plan":
        return  # Repeated topics on different days can be intentional reinforcement.
    seen = set()
    for item in items:
        text = item.question if kind == "quiz" else item.front
        normalized = "".join(
            char
            for char in unicodedata.normalize("NFKC", text).casefold()
            if unicodedata.category(char)[0] in {"L", "M", "N"}
        )
        if not normalized or normalized in seen:
            raise error("invalid_artifact", "Learning output repeats a question or card")
        seen.add(normalized)
