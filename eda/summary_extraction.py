"""Extract official summary topics from Assembly debate transcripts.

The XIe legislature archives mix two different structures in the text stream:
the official table of contents ("sommaire") and headings inside the debate
body.  This module keeps those modes separate and uses the official summary as
the source of truth for ``major_topic_order``, ``major_topic`` and ``subtopic``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd

try:
    from .title_cleaning import clean_title, is_uppercase_title
except ImportError:  # pragma: no cover - notebook/script execution from eda/
    from title_cleaning import clean_title, is_uppercase_title


ExtractionMode = Literal["official_summary", "body_headings"]
LOGGER = logging.getLogger(__name__)


SUMMARY_START_RE = re.compile(r"\bSOMMAIRE\b", re.IGNORECASE)
SUMMARY_END_RE = re.compile(
    r"\b(?:COMPTE\s+RENDU\s+INT[ÉE]GRAL|COMPTE\s+RENDU|PRESIDENCE|PR[ÉE]SIDENCE|S[ÉE]ANCE\s+DU|M\.\s+LE\s+PR[ÉE]SIDENT|La\s+s[ée]ance\s+est\s+ouverte)\b",
    re.IGNORECASE,
)
NUMBERED_TOPIC_RE = re.compile(
    r"^\s*(?P<number>\d{1,2})\s*[,.)-]?\s*(?P<title>[A-ZÀ-ÖØ-Þ0-9][^\n]*)$"
)
PAGE_REF_RE = re.compile(r"(?:\s*(?:\.{2,}|p\.?)\s*\d{1,4})\s*$", re.IGNORECASE)
WRAPPER_RE = re.compile(r"""^[\s\\\"'“”«»]+|[\s\\\"'“”«»]+$""")
SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+")

FALSE_SUBTOPIC_RE = re.compile(
    r"^(?:"
    r"TITRE\s+I(?:ER|er|er)?|"
    r"TITRE\s+I\s+ER|"
    r"ORIENTATIONS\s+ET\s+OBJECTIFS|"
    r"FRACTION\s+DE\s+LA\s+PART\s+NETTE\s+TAXABLE|"
    r"TARIF\s+APPLICABLE$|"
    r"TRANCHES?\s+DE\s+TARIF"
    r")\b",
    re.IGNORECASE,
)
TABLE_LIKE_RE = re.compile(r"\b(?:TARIF|FRACTION|PART\s+NETTE|TAXABLE|N[' ]EXC[ÉE]DANT|%)\b")
GENERIC_LEGAL_RE = re.compile(r"^(?:ARTICLE|TITRE|CHAPITRE|SECTION)\s+[IVXLCDM\d]+(?:ER|E)?$", re.IGNORECASE)
PROCEDURAL_DETAIL_RE = re.compile(
    r"^(?:M\.|MM\.|MMES?\.?|MADAME|MONSIEUR|AMENDEMENTS?|QUESTION\s+DE|REJET|ADOPTION|SCRUTIN|RAPPEL\s+AU\s+R[ÈE]GLEMENT\s+DE\s+M\.)\b",
    re.IGNORECASE,
)
SESSION_RE = re.compile(r"\b(?P<number>\d{1,3})(?:E|ÈME|EME)?\s+S[ÉE]ANCE\b", re.IGNORECASE)

ACCENT_FIXES = {
    "ABROGATION": "ABROGATION",
    "AUDIOVISUEL": "AUDIOVISUEL",
    "EPERNAY": "ÉPERNAY",
    "REGLEMENT": "RÈGLEMENT",
    "REIMS": "REIMS",
    "REFORME": "RÉFORME",
    "SECURITE": "SÉCURITÉ",
    "WARTSILA": "WÄRTSILÄ",
}


@dataclass(frozen=True)
class SummaryEntry:
    structure_level: Literal["major_topic", "subtopic"]
    major_topic_order: int
    major_topic_number: int
    major_topic: str
    subtopic: str | None = None
    source_text: str | None = None
    warning: str | None = None


def extract_text_from_pdf(pdf_path_or_url: str | Path) -> str:
    """Extract text from a local PDF path.

    URLs are deliberately not downloaded here so callers keep network/cache
    policy explicit.  Install either ``pypdf`` or ``pdfminer.six`` for local PDF
    extraction.
    """
    source = str(pdf_path_or_url)
    if re.match(r"^https?://", source):
        raise ValueError("Download the PDF first; extract_text_from_pdf expects a local file path.")

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        PdfReader = None

    if PdfReader is not None:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    try:
        from pdfminer.high_level import extract_text  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install pypdf or pdfminer.six to extract PDF text.") from exc

    return extract_text(str(path))


def normalize_ocr_text(value: object) -> str:
    """Normalize common OCR/typographic artifacts without changing semantics."""
    if value is None or pd.isna(value):
        return ""

    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\u00ad", "")
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = text.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    text = re.sub(r'[\\""]{2,}', '"', text)
    text = WRAPPER_RE.sub("", text).strip()

    accent_replacements = [
        (r"([Aa])\s*[´\u0301]\s*", r"Á"),
        (r"([Ee])\s*[´\u0301]\s*", r"É"),
        (r"([Ii])\s*[´\u0301]\s*", r"Í"),
        (r"([Oo])\s*[´\u0301]\s*", r"Ó"),
        (r"([Uu])\s*[´\u0301]\s*", r"Ú"),
        (r"([Aa])\s*[`\u0300]\s*", r"À"),
        (r"([Ee])\s*[`\u0300]\s*", r"È"),
        (r"([AaEeIiOoUu])\s*[¨\u0308]\s*", lambda m: m.group(1).upper().translate(str.maketrans("AEIOU", "ÄËÏÖÜ"))),
        (r"([Cc])\s*,\s*", r"Ç"),
    ]
    for pattern, replacement in accent_replacements:
        text = re.sub(pattern, replacement, text)

    text = SPACE_RE.sub(" ", text).strip()
    text = re.sub(r"\bI\s+er\b", "Ier", text, flags=re.IGNORECASE)
    text = clean_title(text)

    for source, target in ACCENT_FIXES.items():
        text = re.sub(rf"\b{source}\b", target, text, flags=re.IGNORECASE)

    return SPACE_RE.sub(" ", text).strip(" ,;")


def _raw_lines(text_or_lines: str | Iterable[str]) -> list[str]:
    if isinstance(text_or_lines, str):
        return text_or_lines.splitlines()
    return [str(line) for line in text_or_lines]


def detect_summary_zone(
    text_or_lines: str | Iterable[str],
    target_session_number: int | None = None,
) -> list[str]:
    """Return lines belonging to the official summary zone only."""
    lines = [normalize_ocr_text(line) for line in _raw_lines(text_or_lines)]
    lines = [line for line in lines if line]

    start = _find_summary_start(lines, target_session_number)
    zone: list[str] = []
    seen_topic = False

    for line in lines[start + 1 :]:
        if NUMBERED_TOPIC_RE.match(line):
            seen_topic = True
        if seen_topic and SUMMARY_END_RE.search(line):
            break
        if seen_topic or _is_summary_candidate(line):
            zone.append(line)

    return _drop_layout_noise(zone)


def split_accidentally_merged_major_topics(line: str) -> list[str]:
    """Split OCR lines where two summary entries have been glued together."""
    cleaned = normalize_ocr_text(line)
    if not cleaned:
        return []

    cleaned = re.sub(r"\)\s+(?=\d{1,2}\s*[,.)-]?\s+[A-ZÀ-ÖØ-Þ])", "\n", cleaned)
    cleaned = re.sub(r"(?<=[,;])\s+(?=\d{1,2}\s*[,.)-]?\s+[A-ZÀ-ÖØ-Þ])", "\n", cleaned)
    cleaned = re.sub(
        r"\s+(?=\d{1,2}\s*[,.)-]?\s+(?:QUESTIONS|ORDRE|FAIT|D[ÉE]P[ÔO]T|RAPPELS?|PACTE|LOI|MODIFICATION|COMMUNICATION)\b)",
        "\n",
        cleaned,
    )
    return [part.strip(" )") for part in cleaned.splitlines() if part.strip(" )")]


def split_accidentally_merged_lines(line: str) -> list[str]:
    """Backward-compatible alias for split_accidentally_merged_major_topics."""
    return split_accidentally_merged_major_topics(line)


def repair_wrapped_summary_lines(lines: Iterable[str]) -> list[str]:
    """Join wrapped uppercase summary titles while keeping new topics separate."""
    repaired: list[str] = []

    for original_line in lines:
        for line in split_accidentally_merged_major_topics(original_line):
            line = _strip_page_reference(line)
            if not line:
                continue

            if _is_wrapped_continuation(line, repaired):
                repaired[-1] = f"{repaired[-1]} {line}"
                continue

            repaired.append(line)

    return repaired


def repair_wrapped_lines(lines: Iterable[str]) -> list[str]:
    """Backward-compatible alias for repair_wrapped_summary_lines."""
    return repair_wrapped_summary_lines(lines)


def classify_summary_entries(lines: Iterable[str]) -> pd.DataFrame:
    """Classify official summary lines into major topics and subtopics."""
    entries: list[SummaryEntry] = []
    current_major: SummaryEntry | None = None

    for line in repair_wrapped_summary_lines(lines):
        numbered = NUMBERED_TOPIC_RE.match(line)
        if numbered:
            number = int(numbered.group("number"))
            title = _normalize_topic_title(numbered.group("title"))
            current_major = SummaryEntry(
                structure_level="major_topic",
                major_topic_order=number,
                major_topic_number=number,
                major_topic=title,
                source_text=line,
            )
            entries.append(current_major)
            continue

        if current_major is None or _is_procedural_detail(line) or not _is_summary_candidate(line):
            continue

        title = _normalize_topic_title(line)
        warning = None
        if _looks_like_ambiguous_internal_heading(title):
            warning = "ambiguous_internal_heading"
        entries.append(
            SummaryEntry(
                structure_level="subtopic",
                major_topic_order=current_major.major_topic_order,
                major_topic_number=current_major.major_topic_number,
                major_topic=current_major.major_topic,
                subtopic=title,
                source_text=line,
                warning=warning,
            )
        )

    return pd.DataFrame([entry.__dict__ for entry in entries])


def filter_false_subtopics(summary: pd.DataFrame, *, official_summary: bool = True) -> pd.DataFrame:
    """Remove body-only false positives; keep ambiguous official entries with warnings."""
    if summary.empty:
        return summary

    output = summary.copy()
    if "warning" not in output.columns:
        output["warning"] = None

    is_subtopic = output["structure_level"].eq("subtopic")
    titles = output["subtopic"].fillna("")
    false_like = titles.map(_looks_like_false_subtopic)

    false_rows = output.loc[is_subtopic & false_like, ["source_text", "subtopic"]]
    for row in false_rows.itertuples(index=False):
        LOGGER.warning("Filtered false summary subtopic: %s", row.source_text or row.subtopic)

    return output.loc[~(is_subtopic & false_like)].reset_index(drop=True)


def extract_official_summary_structure(
    text_or_lines: str | Iterable[str],
    target_session_number: int | None = None,
) -> pd.DataFrame:
    """Full official-summary pipeline used for topic CSV generation."""
    zone = detect_summary_zone(text_or_lines, target_session_number=target_session_number)
    classified = classify_summary_entries(zone)
    return filter_false_subtopics(classified, official_summary=True)


def extract_body_heading_structure(text_or_lines: str | Iterable[str]) -> pd.DataFrame:
    """Explicit fallback mode for headings found in the debate body."""
    lines = [normalize_ocr_text(line) for line in _raw_lines(text_or_lines)]
    classified = classify_summary_entries(lines)
    return filter_false_subtopics(classified, official_summary=False)


def export_topics_csv(summary: pd.DataFrame, output_path: str | Path) -> None:
    """Export the stable topic CSV columns."""
    columns = ["major_topic_order", "major_topic", "subtopic"]
    summary.loc[:, columns].drop_duplicates().to_csv(output_path, index=False)


def _drop_layout_noise(lines: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        if re.fullmatch(r"\d{1,4}", line):
            continue
        if re.fullmatch(r"[.,;:() -]+", line):
            continue
        if re.match(r"^ASSEMBL[ÉE]E NATIONALE\b", line, flags=re.IGNORECASE):
            continue
        cleaned.append(line)
    return cleaned


def _find_summary_start(lines: list[str], target_session_number: int | None) -> int:
    summary_indexes = [
        index for index, line in enumerate(lines) if SUMMARY_START_RE.search(line)
    ]
    if not summary_indexes:
        return 0
    if target_session_number is None:
        return summary_indexes[0]

    for summary_index in summary_indexes:
        context_start = max(0, summary_index - 12)
        context = " ".join(lines[context_start : summary_index + 1])
        if _context_matches_session(context, target_session_number):
            return summary_index

    LOGGER.warning(
        "No SOMMAIRE matched session %s; using first summary zone.",
        target_session_number,
    )
    return summary_indexes[0]


def _context_matches_session(context: str, target_session_number: int) -> bool:
    normalized_context = normalize_ocr_text(context)
    for match in SESSION_RE.finditer(normalized_context):
        if int(match.group("number")) == target_session_number:
            return True

    return bool(
        re.search(
            rf"\b(?:N[°O]\s*)?{target_session_number}\b",
            normalized_context,
            flags=re.IGNORECASE,
        )
    )


def _strip_page_reference(line: str) -> str:
    match = NUMBERED_TOPIC_RE.match(line)
    if match:
        title = _strip_numbered_page_reference(match.group("title")).strip()
        return f"{match.group('number')} {title}".strip()
    return PAGE_REF_RE.sub("", line).strip()


def _is_wrapped_continuation(line: str, repaired: list[str]) -> bool:
    if not repaired or NUMBERED_TOPIC_RE.match(line):
        return False
    if not _is_summary_candidate(line):
        return False

    previous = repaired[-1]
    if not _is_summary_candidate(previous):
        return False
    if _looks_like_new_major_without_number(line):
        return False
    if _looks_like_wrapped_fragment(line):
        return True
    if _ends_with_open_connector(previous):
        return True
    if _ends_like_complete_title(previous) and len(previous) < 70:
        return False
    return False


def _strip_numbered_page_reference(title: str) -> str:
    stripped = PAGE_REF_RE.sub("", title).strip()
    if stripped != title.strip():
        return stripped

    match = re.search(r"\s+\d{1,4}$", title.strip())
    if not match:
        return title

    without_last_number = title[: match.start()].rstrip()
    previous_token = without_last_number.rsplit(" ", 1)[-1].upper()
    if previous_token in {"POUR", "EN", "DE", "DU", "DES", "ARTICLE", "RN"}:
        return title
    return without_last_number


def _is_summary_candidate(line: str) -> bool:
    cleaned = normalize_ocr_text(line)
    if not cleaned or len(cleaned) > 220:
        return False
    if _is_procedural_detail(cleaned):
        return False
    if cleaned.endswith((".", "!", "?", ":")):
        return False
    words = WORD_RE.findall(cleaned)
    if len(words) < 2:
        return False
    return is_uppercase_title(cleaned, threshold=0.70)


def _is_procedural_detail(line: str) -> bool:
    return bool(PROCEDURAL_DETAIL_RE.match(normalize_ocr_text(line)))


def _looks_like_wrapped_fragment(line: str) -> bool:
    normalized = _normalize_topic_title(line)
    return normalized.startswith(
        (
            "A ",
            "À ",
            "AU ",
            "AUX ",
            "D'",
            "DE ",
            "DU ",
            "DES ",
            "ENTRE ",
            "ET ",
            "OU ",
            "POUR ",
            "RELATIF ",
            "RELATIVE ",
            "RELATIFS ",
            "RELATIVES ",
            "SUR ",
        )
    )


def _ends_with_open_connector(line: str) -> bool:
    normalized = _normalize_topic_title(line)
    return bool(
        re.search(
            r"\b(?:A|À|AU|AUX|D|DE|DU|DES|ET|OU|POUR|RELATIF|RELATIVE|SUR|LA|LE|LES|L')$",
            normalized,
        )
    )


def _looks_like_new_major_without_number(line: str) -> bool:
    normalized = _normalize_topic_title(line)
    starters = (
        "QUESTIONS AU GOUVERNEMENT",
        "QUESTIONS ORALES SANS DÉBAT",
        "PACTE CIVIL DE SOLIDARITÉ",
        "LOI DE FINANCEMENT",
        "RAPPELS AU RÈGLEMENT",
        "ORDRE DU JOUR",
    )
    return normalized.startswith(starters)


def _ends_like_complete_title(line: str) -> bool:
    normalized = _normalize_topic_title(line)
    if normalized.endswith((",", "-", "'")):
        return False
    return len(WORD_RE.findall(normalized)) <= 8


def _normalize_topic_title(title: str) -> str:
    title = normalize_ocr_text(title)
    title = re.sub(r"^\d{1,2}\s*[,.)-]?\s*", "", title)
    title = _strip_page_reference(title)
    title = title.strip(" ,;")
    return clean_title(title)


def _looks_like_false_subtopic(title: str) -> bool:
    normalized = _normalize_topic_title(title)
    if FALSE_SUBTOPIC_RE.search(normalized):
        return True
    if GENERIC_LEGAL_RE.match(normalized):
        return True
    if TABLE_LIKE_RE.search(normalized) and len(WORD_RE.findall(normalized)) <= 10:
        return True
    return False


def _looks_like_ambiguous_internal_heading(title: str) -> bool:
    return _looks_like_false_subtopic(title)
