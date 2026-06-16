from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

C1_CONTROL_RE = re.compile(r"[\u0080-\u009f]+")


def run_internal_assertions() -> None:
    return None


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(root: ET.Element, tag_name: str) -> str | None:
    for element in root.iter():
        if _tag_name(element.tag) == tag_name and element.text:
            return _clean_text(element.text)
    return None


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = C1_CONTROL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _node_text(node: ET.Element, *, exclude_tags: set[str] | None = None) -> str:
    exclude_tags = exclude_tags or set()
    parts: list[str] = []

    def visit(element: ET.Element) -> None:
        if _tag_name(element.tag) not in exclude_tags and element.text:
            parts.append(element.text)
        for child in element:
            visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return _clean_text("".join(parts))


def _child_text(node: ET.Element, tag_name: str) -> str | None:
    for child in node:
        if _tag_name(child.tag) == tag_name:
            return _node_text(child)
    return None


def _attributes(node: ET.Element) -> dict[str, str]:
    return {key: value for key, value in node.attrib.items() if value is not None}


def _orateur(node: ET.Element) -> dict[str, Any] | list[dict[str, Any]] | None:
    speakers = []
    for child in node:
        if _tag_name(child.tag) != "Orateur":
            continue
        speaker = {
            "attributes": _attributes(child),
            "Nom": _child_text(child, "Nom") or _node_text(child),
        }
        if not speaker["Nom"]:
            speaker["Nom"] = None
        speakers.append(speaker)
    if not speakers:
        return None
    if len(speakers) == 1:
        return speakers[0]
    return speakers


def _role(node: ET.Element) -> list[str]:
    roles = []
    for child in node:
        if _tag_name(child.tag) == "QualiteMouvement":
            text = _node_text(child)
            if text:
                roles.append(text)
    return roles


def _para_entry(node: ET.Element, section: str | None, subtopic1: str | None, subtopic2: str | None) -> dict[str, Any]:
    para_text = _node_text(node, exclude_tags={"Orateur"})
    entry: dict[str, Any] = {
        "Ident": node.attrib.get("Ident"),
        "Para": para_text,
        "Para_clean": para_text,
        "section": section,
        "sous_section_1": subtopic1,
        "sous_section_2": subtopic2,
    }

    speaker = _orateur(node)
    if speaker:
        entry["Orateur"] = speaker

    roles = _role(node)
    if roles:
        entry["QualiteMouvement"] = {"role": roles}

    return entry


def _iter_content_nodes(root: ET.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    section: str | None = None
    subtopic1: str | None = None
    subtopic2: str | None = None

    def visit(node: ET.Element) -> None:
        nonlocal section, subtopic1, subtopic2

        tag = _tag_name(node.tag)
        previous = (section, subtopic1, subtopic2)

        if tag == "Section":
            subtopic1 = None
            subtopic2 = None
            title = _section_title(node)
            if title:
                section = title
        elif tag == "SousSection1":
            subtopic2 = None
            title = _section_title(node)
            if title:
                subtopic1 = title
        elif tag == "SousSection2":
            title = _section_title(node)
            if title:
                subtopic2 = title
        elif tag == "Para":
            text = _node_text(node, exclude_tags={"Orateur"})
            if text:
                rows.append(_para_entry(node, section, subtopic1, subtopic2))
            return

        for child in node:
            child_tag = _tag_name(child.tag)
            if child_tag in {"Sommaire", "Quantiemes"}:
                continue
            visit(child)

        if tag in {"Section", "SousSection1", "SousSection2"}:
            section, subtopic1, subtopic2 = previous

    visit(root)
    return rows


def _section_title(node: ET.Element) -> str | None:
    for child in node:
        if _tag_name(child.tag) == "TitreStruct":
            title = _node_text(child)
            if title:
                return title
    return None


def _source_files(cri_file: Path) -> list[str]:
    sources = []
    aaa_file = cri_file.with_name(cri_file.name.replace("CRI_", "AAA_", 1))
    if aaa_file.exists():
        sources.append(aaa_file.name)
    sources.append(cri_file.name)
    return sources


def _output_dir(raw_dir: Path, converted_dir: Path, cri_file: Path) -> Path:
    relative_parent = cri_file.parent.relative_to(raw_dir)
    if relative_parent.name == cri_file.parent.name and relative_parent.parts[-1].isdigit():
        session_dir = f"AN_{cri_file.stem.removeprefix('CRI_')}"
        return converted_dir / relative_parent / session_dir
    return converted_dir / relative_parent


def _date_filename(date_seance: str | None, fallback_stem: str) -> str:
    if date_seance:
        date_part = date_seance.split("+", 1)[0].split("T", 1)[0]
        if date_part:
            return date_part
    match = re.search(r"(\d{4})(\d{2})(\d{2})", fallback_stem)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return fallback_stem.removeprefix("CRI_")


def _convert_file(raw_dir: Path, converted_dir: Path, cri_file: Path) -> bool:
    root = ET.parse(cri_file).getroot()
    date_seance = _first_text(root, "dateSeance")
    output_dir = _output_dir(raw_dir, converted_dir, cri_file)
    date_name = _date_filename(date_seance, cri_file.stem)
    speech_file = output_dir / f"speech_text_{date_name}.json"
    metadata_file = output_dir / f"metadata_{date_name}.json"

    if speech_file.exists():
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "source_files": _source_files(cri_file),
        "dateSeance": date_seance,
        "numSeance": _first_text(root, "numSeance"),
        "Para": _iter_content_nodes(root),
    }
    metadata = {
        "source_files": _source_files(cri_file),
        "Metadonnees": {
            "dateSeance": date_seance,
            "numSeance": _first_text(root, "numSeance"),
            "numJourSession": _first_text(root, "numJourSession"),
        },
    }

    with speech_file.open("w", encoding="utf-8") as output:
        json.dump(document, output, ensure_ascii=False, indent=2)
        output.write("\n")
    with metadata_file.open("w", encoding="utf-8") as output:
        json.dump(metadata, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return True


def convert(raw_dir: Path, converted_dir: Path, *, log_samples: bool = False) -> None:
    converted = 0
    skipped = 0
    failed = 0
    for cri_file in sorted(raw_dir.rglob("CRI_*.xml")):
        try:
            was_converted = _convert_file(raw_dir, converted_dir, cri_file)
        except ET.ParseError as error:
            failed += 1
            print(f"XML ignore, parsing impossible: {cri_file} ({error})")
            continue
        if was_converted:
            converted += 1
            if log_samples and converted <= 5:
                print(f"converti: {cri_file}")
        else:
            skipped += 1

    print(f"XML CRI convertis: {converted}")
    print(f"JSON deja presents: {skipped}")
    print(f"XML ignores: {failed}")
