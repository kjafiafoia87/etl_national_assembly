"""Utilities for cleaning extracted parliamentary titles."""

from __future__ import annotations

import re


LETTER_RE = r"A-Za-zÀ-ÖØ-öø-ÿ"
APOSTROPHE_SPACE_RE = re.compile(rf"([{LETTER_RE}])'\s+([{LETTER_RE}])")
FAULTY_CONTRACTION_RE = re.compile(
    r"\b(?:[àÀ]\s+les|[àÀ]\s+le|de\s+les|de\s+le)\b",
    flags=re.IGNORECASE,
)


def is_uppercase_title(text: str, threshold: float = 0.8) -> bool:
    """Return True when alphabetic characters are mostly uppercase."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False

    uppercase_letters = [
        char for char in letters if char.upper() == char and char.lower() != char
    ]
    return len(uppercase_letters) / len(letters) >= threshold


def clean_title(title: str) -> str:
    """Fix French detokenization artifacts in extracted titles only."""
    context_without_faulty_contractions = FAULTY_CONTRACTION_RE.sub(" ", title)
    upper_context = is_uppercase_title(title) or is_uppercase_title(
        context_without_faulty_contractions
    )

    replacements = [
        (r"\b[àÀ]\s+les\b", "AUX", "aux"),
        (r"\b[àÀ]\s+le\b", "AU", "au"),
        (r"\bde\s+les\b", "DES", "des"),
        (r"\bde\s+le\b", "DU", "du"),
    ]

    cleaned = title
    for pattern, upper_replacement, lower_replacement in replacements:
        cleaned = re.sub(
            pattern,
            lambda match: (
                upper_replacement
                if upper_context or is_uppercase_title(match.group(0), threshold=0.8)
                else lower_replacement
            ),
            cleaned,
            flags=re.IGNORECASE,
        )

    return APOSTROPHE_SPACE_RE.sub(r"\1'\2", cleaned)
