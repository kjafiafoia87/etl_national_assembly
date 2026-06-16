"""Filters for keeping genuine parliamentary reactions."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


WRAPPER_RE = re.compile(r"""^[\s\\\"'“”«»]+|[\s\\\"'“”«»]+$""")
SPACE_RE = re.compile(r"\s+")

REACTION_RE = re.compile(
    r"\b(?:"
    r"applaudissements?|applaudit|applaudissent|"
    r"sourires?|rires?|"
    r"murmures?|exclamations?|protestations?|"
    r"brouhaha|interruptions?|"
    r"huées?|vives?\s+réactions?|"
    r"mouvements?|marques?\s+d['’ ](?:approbation|assentiment)|"
    r"très\s+bien|bravo|bien\s+dit|ah|oh|oui|non|c['’ ]est\s+vrai"
    r")\b",
    flags=re.IGNORECASE,
)

NON_REACTION_RE = re.compile(
    r"\b(?:"
    r"n\s*o?s?\s*\d|rapport\s+n\s*o|"
    r"exception\s+d['’ ]irrecevabilité|"
    r"question\s+préalable|"
    r"la\s+séance\s+est\s+(?:ouverte|suspendue|reprise|levée)|"
    r"ordre\s+du\s+jour"
    r")\b",
    flags=re.IGNORECASE,
)


def normalize_interjection_text(value: Any) -> str:
    """Remove archive wrappers while preserving the source wording."""
    if pd.isna(value):
        return ""

    text = str(value).strip()
    text = WRAPPER_RE.sub("", text).strip()
    text = SPACE_RE.sub(" ", text)
    return text


def is_reaction_interjection(value: Any) -> bool:
    """Return True for real reactions, not structural false positives."""
    text = normalize_interjection_text(value)
    if not text:
        return False

    if NON_REACTION_RE.search(text) and not REACTION_RE.search(text):
        return False

    return REACTION_RE.search(text) is not None


def filter_reaction_interjections(
    frame: pd.DataFrame,
    text_col: str = "text",
    interjection_col: str = "interjection",
) -> pd.DataFrame:
    """Keep rows flagged as interjections only when they are real reactions."""
    if text_col not in frame.columns:
        raise KeyError(f"Colonne texte absente: {text_col!r}")
    if interjection_col not in frame.columns:
        raise KeyError(f"Colonne interjection absente: {interjection_col!r}")

    flagged = frame[interjection_col].eq(True)
    reactions = frame[text_col].map(is_reaction_interjection)
    return frame[flagged & reactions].copy()
