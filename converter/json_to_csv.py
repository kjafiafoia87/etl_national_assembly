from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from converter.convert import _clean_text


FIELDNAMES = [
    "source_files",
    "id",
    "date",
    "text_speech_brut",
    "text_speech_clean",
    "topic",
    "subtopic1",
    "subtopic2",
    "speaker",
    "link_speaker",
    "role",
    "gender",
    "speech_interjection",
    "quote",
    "numSeance",
]


def _value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ";".join(_clean_text(str(item)) for item in value if item is not None)
    return _clean_text(str(value))


def _format_date(date_value: str) -> str:
    if not date_value:
        return ""
    date_part = date_value.split("+", 1)[0]
    date_part = date_part.split("T", 1)[0]
    parts = date_part.split("-")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _speaker_values(speaker: Any, key: str) -> str:
    values = []
    for item in _as_list(speaker):
        if isinstance(item, dict):
            values.append(item.get(key))
    return _value(values)


def _speaker_attribute_values(speaker: Any, key: str) -> str:
    values = []
    for item in _as_list(speaker):
        if isinstance(item, dict):
            attributes = item.get("attributes") or {}
            if isinstance(attributes, dict):
                values.append(attributes.get(key))
    return _value(values)


def _speech_files(converted_dir: Path) -> list[Path]:
    return sorted(converted_dir.rglob("speech_text_*.json"))


def iter_rows(converted_dir: Path) -> Iterable[dict[str, str]]:
    for speech_file in _speech_files(converted_dir):
        with speech_file.open(encoding="utf-8") as input_file:
            document = json.load(input_file)
        source_files = _value(document.get("source_files"))
        date = _format_date(_value(document.get("dateSeance")))
        num_seance = _value(document.get("numSeance"))
        for para in document.get("Para", []):
            speaker = para.get("Orateur") or {}
            yield {
                "source_files": source_files,
                "id": _value(para.get("Ident")),
                "date": date,
                "text_speech_brut": _value(para.get("Para")),
                "text_speech_clean": _value(para.get("Para_clean")),
                "topic": _value(para.get("section")),
                "subtopic1": _value(para.get("sous_section_1")),
                "subtopic2": _value(para.get("sous_section_2")),
                "speaker": _speaker_values(speaker, "Nom"),
                "link_speaker": _speaker_attribute_values(speaker, "href"),
                "role": _speaker_values(speaker, "role") or _value(para.get("role")),
                "gender": _speaker_values(speaker, "gender") or _value(para.get("gender")),
                "speech_interjection": _value(para.get("speech_interjection") or para.get("interjection")),
                "quote": _value(para.get("quote")),
                "numSeance": num_seance,
            }


def write_csv(rows: Iterable[dict[str, str]], csv_file: Path) -> int:
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with csv_file.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count
