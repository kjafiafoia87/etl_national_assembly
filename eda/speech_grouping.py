"""Group consecutive speeches and attach reaction interjections."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

try:
    from .interjection_filter import is_reaction_interjection, normalize_interjection_text
except ImportError:  # pragma: no cover - notebook/script execution from eda/
    from interjection_filter import is_reaction_interjection, normalize_interjection_text


WRAPPER_RE = re.compile(r"""^[\s\\\"'“”«»]+|[\s\\\"'“”«»]+$""")
SPACE_RE = re.compile(r"\s+")


def normalize_speech_text(value: Any) -> str:
    """Remove archive wrappers and collapse whitespace."""
    if pd.isna(value):
        return ""

    text = str(value).strip()
    text = WRAPPER_RE.sub("", text).strip()
    return SPACE_RE.sub(" ", text)


def _clean_scalar(value: Any) -> Any:
    return None if pd.isna(value) else value


def _is_true(value: Any) -> bool:
    return bool(value) if not pd.isna(value) else False


def _update_context(group: dict[str, Any], row: pd.Series) -> None:
    for column in ("major_topic_order", "major_topic", "subtopic"):
        value = _clean_scalar(row.get(column))
        if value is not None:
            group[column] = value


def _speaker_key(row: pd.Series, row_order: int) -> tuple[Any, ...]:
    speaker = _clean_scalar(row.get("speaker"))
    role = _clean_scalar(row.get("role"))
    if speaker:
        return ("speaker", speaker, role)

    # Missing speakers are often ambiguous in the source; avoid merging them
    # unless a caller later supplies a more reliable speaker identifier.
    return ("missing-speaker", row_order)


def _procedure_text(row: pd.Series, text_col: str, procedure_type: str | None) -> str:
    if procedure_type == "major_topic":
        return normalize_speech_text(row.get("major_topic")) or normalize_speech_text(
            row.get(text_col)
        )
    if procedure_type == "subtopic":
        return normalize_speech_text(row.get("subtopic")) or normalize_speech_text(
            row.get(text_col)
        )
    return normalize_speech_text(row.get(text_col))


def _start_group(
    row: pd.Series,
    row_order: int,
    text_col: str,
    row_type: str = "speech",
    procedure_type: str | None = None,
) -> dict[str, Any]:
    speech_text = (
        _procedure_text(row, text_col, procedure_type)
        if row_type == "procedure"
        else normalize_speech_text(row.get(text_col))
    )
    return {
        "speech_order": None,
        "row_type": row_type,
        "procedure_type": procedure_type,
        "first_row_order": row_order,
        "last_row_order": row_order,
        "source_row_orders": [row_order],
        "source_ids": [_clean_scalar(row.get("id"))],
        "speaker": _clean_scalar(row.get("speaker")),
        "role": _clean_scalar(row.get("role")),
        "party": _clean_scalar(row.get("party")),
        "parliamentary_group": _clean_scalar(row.get("parliamentary_group")),
        "date": _clean_scalar(row.get("date")),
        "session": _clean_scalar(row.get("session")),
        "agenda_item": _clean_scalar(row.get("agenda_item")),
        "major_topic_order": _clean_scalar(row.get("major_topic_order")),
        "major_topic": _clean_scalar(row.get("major_topic")),
        "subtopic": _clean_scalar(row.get("subtopic")),
        "speech_text": speech_text,
        "interjections": [],
        "_speaker_key": _speaker_key(row, row_order),
    }


def _append_speech(group: dict[str, Any], row: pd.Series, row_order: int, text_col: str) -> None:
    text = normalize_speech_text(row.get(text_col))
    if text:
        group["speech_text"] = (
            f"{group['speech_text']} {text}".strip()
            if group["speech_text"]
            else text
        )
    group["last_row_order"] = row_order
    group["source_row_orders"].append(row_order)
    group["source_ids"].append(_clean_scalar(row.get("id")))
    _update_context(group, row)


def _append_interjection(group: dict[str, Any], row: pd.Series, row_order: int, text_col: str) -> None:
    group["interjections"].append(normalize_interjection_text(row.get(text_col)))
    group["last_row_order"] = row_order
    group["source_row_orders"].append(row_order)
    group["source_ids"].append(_clean_scalar(row.get("id")))
    _update_context(group, row)


def _finalize_groups(groups: list[dict[str, Any]]) -> pd.DataFrame:
    public_groups = []
    for index, group in enumerate(groups, start=1):
        public_group = {key: value for key, value in group.items() if not key.startswith("_")}
        public_group["speech_order"] = index
        public_groups.append(public_group)
    return pd.DataFrame(public_groups)


def group_consecutive_speeches(
    frame: pd.DataFrame,
    text_col: str = "text",
    interjection_col: str = "interjection",
    source_order_col: str | None = None,
    procedure_col: str | None = None,
    procedure_values: set[str] | None = None,
) -> pd.DataFrame:
    """Group consecutive speech rows and attach genuine reactions.

    Reaction interjections are not emitted as standalone speeches when they can
    be attached to the current speech group. Rows whose procedure column is in
    procedure_values are emitted as standalone procedure rows and break speech
    grouping.
    """
    if text_col not in frame.columns:
        raise KeyError(f"Colonne texte absente: {text_col!r}")
    if interjection_col not in frame.columns:
        raise KeyError(f"Colonne interjection absente: {interjection_col!r}")
    if procedure_col is not None and procedure_col not in frame.columns:
        raise KeyError(f"Colonne procedure absente: {procedure_col!r}")

    procedure_values = procedure_values or {"major_topic", "subtopic"}
    groups: list[dict[str, Any]] = []
    current_group: dict[str, Any] | None = None

    for fallback_order, (_, row) in enumerate(frame.iterrows(), start=1):
        row_order = (
            _clean_scalar(row.get(source_order_col))
            if source_order_col is not None and source_order_col in frame.columns
            else fallback_order
        )
        procedure_type = (
            _clean_scalar(row.get(procedure_col))
            if procedure_col is not None
            else None
        )
        if procedure_type in procedure_values:
            groups.append(
                _start_group(
                    row,
                    row_order,
                    text_col,
                    row_type="procedure",
                    procedure_type=procedure_type,
                )
            )
            current_group = None
            continue

        is_reaction = _is_true(row.get(interjection_col)) and is_reaction_interjection(
            row.get(text_col)
        )

        if is_reaction:
            if current_group is None:
                current_group = _start_group(row, row_order, text_col)
                current_group["speech_text"] = ""
                current_group["source_row_orders"] = []
                current_group["source_ids"] = []
                groups.append(current_group)
            _append_interjection(current_group, row, row_order, text_col)
            continue

        row_key = _speaker_key(row, row_order)
        if current_group is None or current_group["_speaker_key"] != row_key:
            current_group = _start_group(row, row_order, text_col)
            groups.append(current_group)
            continue

        _append_speech(current_group, row, row_order, text_col)

    return _finalize_groups(groups)
