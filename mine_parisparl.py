#!/usr/bin/env python
# coding: utf-8

# In[2]:


from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from title_cleaning import clean_title


# In[3]:


df = pd.read_csv('../data/speech/1996_2019/parisparl_reden_1998.csv')

df['date'] = pd.to_datetime(df['date'], errors='coerce')

# Jour test pour construire les regles de structure.
one_day_speech = df[df['date'].eq(pd.Timestamp('1998-11-25'))].copy()
one_day_speech


# In[4]:


# Vue utile pour inspecter les lignes marquees comme interjections,
# sans perdre les discours qui doivent heriter du sujet/sous-sujet courant.
one_day_interjections = one_day_speech[one_day_speech['interjection'].eq(True)].copy()
one_day_interjections


# ## Preprocessing de la structure du debat
# 
# Objectif: recuperer proprement la structure d'une journee de debat a partir de `one_day_speech`.
# 
# Regles de depart:
# 
# - un **grand sujet** commence par un numero suivi d'un titre majoritairement en capitales, par exemple `1 SOUHAITS DE BIENVENUE...`;
# - un **sous-sujet** est une ligne courte, sans numero, majoritairement en capitales, par exemple `TAUX DE CONVERSION DE L' EURO`;
# - les lignes suivantes heritent du dernier grand sujet et du dernier sous-sujet detectes.
# 

# In[5]:


MAJOR_TOPIC_RE = re.compile(r"^\s*(?P<number>\d{1,2})\s+(?P<title>.+?)\s*$")
INLINE_MAJOR_TOPIC_RE = re.compile(r"(?:^|[.!?]\s+)(?P<number>\d{1,2})\s+(?P<title>.+?)\s*$")
TRAILING_MAJOR_DETAIL_RE = re.compile(
    r"\s+(?:Explications de vote|Discussion générale|Suite de la discussion|Discussion d['’ ]un|Vote sur).*$"
)
WRAPPER_RE = re.compile(r"""^[\s\\\"'“”«»]+|[\s\\\"'“”«»]+$""")
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+")
INLINE_TOPIC_RE = re.compile(
    r"\b(?:Nous\s+(?:passons|en\s+revenons|revenons)|On\s+en\s+revient)\b.+?\s+"
    r"(?P<title>[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ' -]+[A-ZÀ-ÖØ-Þ])\s*$",
)


@dataclass(frozen=True)
class TopicMatch:
    number: Optional[int]
    title: str


def clean_structure_text(value: object) -> str:
    """Nettoie les guillemets parasites sans modifier les mots du debat."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = WRAPPER_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def uppercase_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isupper() for char in letters) / len(letters)


def is_parenthetical(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("(") and stripped.endswith(")")


def is_title_like(text: str, min_ratio: float = 0.70, max_chars: int = 180) -> bool:
    text = clean_structure_text(text)
    if not text or is_parenthetical(text):
        return False
    if len(text) > max_chars:
        return False
    if text.endswith((".", "!", "?", ";", ":")):
        return False
    return uppercase_ratio(text) >= min_ratio


def normalize_major_title(title: str) -> str:
    title = TRAILING_MAJOR_DETAIL_RE.sub("", title).strip()
    title = re.sub(r"\bMODIFICATIONDE\b", "MODIFICATION DE", title)
    title = re.sub(r"\bORDONNANCERELATIVE\b", "ORDONNANCE RELATIVE", title)
    title = re.sub(r"\s+", " ", title)
    return clean_title(title)


def match_major_topic(text: object) -> Optional[TopicMatch]:
    cleaned = clean_structure_text(text)
    match = MAJOR_TOPIC_RE.match(cleaned) or INLINE_MAJOR_TOPIC_RE.search(cleaned)
    if not match:
        return None

    title = normalize_major_title(match.group("title"))
    if not is_title_like(title, min_ratio=0.55):
        return None
    return TopicMatch(number=int(match.group("number")), title=title)


def match_subtopic_candidate(text: object) -> Optional[TopicMatch]:
    cleaned = clean_structure_text(text)
    if MAJOR_TOPIC_RE.match(cleaned):
        return None
    if not is_title_like(cleaned, min_ratio=0.75, max_chars=120):
        return None

    words = WORD_RE.findall(cleaned)
    if not 2 <= len(words) <= 14:
        return None
    return TopicMatch(number=None, title=clean_title(cleaned))


def extract_inline_subtopic_text(text: object) -> Optional[str]:
    cleaned = clean_structure_text(text)
    inline_match = INLINE_TOPIC_RE.search(cleaned)
    if inline_match:
        candidate = inline_match.group("title").strip()
        if match_subtopic_candidate(candidate) is not None:
            return candidate

    parts = re.split(r"[.!?;:]\s+", cleaned)
    if len(parts) < 2:
        return None

    candidate = parts[-1].strip()
    if re.search(r"\bla parole est\b", candidate, flags=re.IGNORECASE):
        return None
    if match_subtopic_candidate(candidate) is None:
        return None
    return candidate


def match_subtopic(text: object) -> Optional[TopicMatch]:
    direct_match = match_subtopic_candidate(text)
    if direct_match is not None:
        return direct_match

    inline_text = extract_inline_subtopic_text(text)
    if inline_text is None:
        return None
    return TopicMatch(number=None, title=clean_title(inline_text))


def is_major_topic_continuation(text: object) -> bool:
    cleaned = clean_structure_text(text)
    if not is_title_like(cleaned, min_ratio=0.70, max_chars=80):
        return False
    return cleaned.startswith(("DE ", "DU ", "DES ", "D'", "À ", "A "))

def annotate_debate_structure(one_day_speech: pd.DataFrame, text_col: str = "text") -> pd.DataFrame:
    """Ajoute les colonnes de structure a un dataframe d'une journee de debat."""
    if text_col not in one_day_speech.columns:
        raise KeyError(f"Colonne texte absente: {text_col!r}")

    output = one_day_speech.copy()
    output["structure_text"] = output[text_col].map(clean_structure_text)
    output["structure_level"] = "speech"
    output["major_topic_number"] = pd.NA
    output["major_topic"] = pd.NA
    output["major_topic_order"] = pd.NA
    output["subtopic"] = pd.NA

    major_topic_order = 0
    current_major_number: Optional[int] = None
    current_major_title: Optional[str] = None
    current_major_order: Optional[int] = None
    current_subtopic: Optional[str] = None
    current_major_index = None
    awaiting_major_continuation = False

    for index, row in output.iterrows():
        text = row["structure_text"]

        major = match_major_topic(text)
        if major is not None:
            major_topic_order += 1
            current_major_number = major.number
            current_major_title = major.title
            current_major_order = major_topic_order
            current_subtopic = None
            current_major_index = index
            awaiting_major_continuation = True
            output.at[index, "structure_level"] = "major_topic"
            output.at[index, "major_topic_number"] = major.number
            output.at[index, "major_topic"] = major.title
            output.at[index, "major_topic_order"] = current_major_order
            continue

        if awaiting_major_continuation and is_major_topic_continuation(text):
            current_major_title = clean_title(f"{current_major_title} {text}")
            output.at[index, "structure_level"] = "speech"
            output.at[index, "major_topic_number"] = current_major_number
            output.at[index, "major_topic"] = current_major_title
            output.at[index, "major_topic_order"] = current_major_order
            if current_major_index is not None:
                output.at[current_major_index, "major_topic"] = current_major_title
            continue

        subtopic = match_subtopic(text)
        if subtopic is not None:
            current_subtopic = subtopic.title
            awaiting_major_continuation = False
            output.at[index, "structure_level"] = "subtopic"
        if subtopic is None:
            awaiting_major_continuation = False

        output.at[index, "major_topic_number"] = current_major_number
        output.at[index, "major_topic"] = current_major_title
        output.at[index, "major_topic_order"] = current_major_order
        output.at[index, "subtopic"] = current_subtopic

    return output


def extract_debate_structure(one_day_speech: pd.DataFrame, text_col: str = "text") -> pd.DataFrame:
    annotated = annotate_debate_structure(one_day_speech, text_col=text_col)
    structure_rows = annotated["structure_level"].isin(["major_topic", "subtopic"])
    optional_context_cols = [col for col in ["session", "agenda_item"] if col in annotated.columns]
    structure_cols = [
        "id",
        *optional_context_cols,
        "speaker",
        "interjection",
        "structure_level",
        "major_topic_order",
        "major_topic_number",
        "major_topic",
        "subtopic",
        "structure_text",
    ]
    return annotated.loc[structure_rows, structure_cols]


# In[6]:


annotated_one_day_speech = annotate_debate_structure(one_day_speech)
debate_structure = extract_debate_structure(one_day_speech)

major_topics_check = (
    debate_structure[debate_structure['structure_level'].isin(['major_topic', 'subtopic'])]
    [[col for col in ['structure_level', 'major_topic_order', 'major_topic_number', 'major_topic', 'subtopic', 'session', 'agenda_item', 'id', 'structure_text'] if col in debate_structure.columns]]
    .drop_duplicates(subset=['structure_level', 'major_topic_order', 'major_topic_number', 'major_topic', 'subtopic'])
    .sort_values(['major_topic_order', 'id'])
)
detected_numbers = set(major_topics_check['major_topic_number'].dropna().astype(int))
if detected_numbers:
    expected_numbers = set(range(min(detected_numbers), max(detected_numbers) + 1))
    print('Major topic numbers detected:', sorted(detected_numbers))
    print('Missing major topic numbers:', sorted(expected_numbers - detected_numbers))

print(debate_structure['structure_level'].value_counts())
major_topics_check


# In[ ]:

