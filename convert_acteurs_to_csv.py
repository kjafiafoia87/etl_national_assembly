#!/usr/bin/env python3
"""
Convert Assemblee nationale acteur/organe JSON files to two CSV tables:

  - politician.csv
  - mandate.csv

Usage:
  python3 convert_acteurs_to_csv.py
  python3 convert_acteurs_to_csv.py --actors-dir data/deputes/acteur --organs-dir data/deputes/organe --out-dir tables

Notes on unavailable fields:
  education_level, school, academic_title, languages, list and votes are not
  present in the acteur JSON files used here, so they are exported empty.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import html
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


POLITICIAN_COLUMNS = [
    "mp_id",
    "first_name",
    "last_name",
    "birth_date",
    "birth_place",
    "education_level",
    "school",
    "academic_title",
    "profession",
    "languages",
    "seniority",
    "status",
    "country_id",
]

MANDATE_COLUMNS = [
    "mp_id",
    "term",
    "party_id",
    "club",
    "list",
    "constituency",
    "committees",
    "mandate_start",
    "mandate_end",
    "election_date",
    "votes",
    "source_url",
    "country_id",
]

UNKNOWN_PARTY_ID = "P000"
DEFAULT_TERMS = list(range(10, 18))
SYCOMORE_LIST_URLS = {
    term: f"https://www2.assemblee-nationale.fr/sycomore/liste/{term + 47}?alpha=true"
    for term in DEFAULT_TERMS
}
MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}
ROMAN_TERMS = {
    "X": 10,
    "XI": 11,
    "XII": 12,
    "XIII": 13,
    "XIV": 14,
    "XV": 15,
    "XVI": 16,
    "XVII": 17,
}

LEGACY_CLUB_ALIASES = {
    "socialiste": "SOC",
    # Business convention: party.csv also contains P015/SRC-DVG for the nearby
    # label "Socialiste, radical, citoyen et divers gauche". The historical
    # labels below are intentionally grouped under P008/SOC for this archive.
    "socialiste, radical et citoyen et divers gauche": "SOC",
    "socialiste radical et citoyen et divers gauche": "SOC",
    "apparente socialiste": "SOC",
    "communiste": "GDR",
    "depute-e-s communistes et republicains": "GDR",
    "deputes n'appartenant a aucun groupe": "NI",
    "non inscrit": "NI",
    # Historical RPR rows are intentionally grouped with their UMP successor.
    "rassemblement pour la republique": "UMP",
    "union pour la democratie francaise et du centre": "UDF",
    "union pour un mouvement populaire": "UMP",
}

REPORT_COLUMNS = {
    "fallback_pa_ids.csv": ["mp_id", "sycomore_id", "name", "source_url"],
    "duplicate_politicians.csv": ["mp_id", "kept_source", "discarded_source"],
    "duplicate_mandates.csv": ["mp_id", "term", "kept_source", "discarded_source"],
    "unresolved_party_ids.csv": ["mp_id", "term", "club", "source_url"],
}


@dataclass
class DeputyLink:
    name: str
    url: str
    sycomore_id: str


@dataclass
class ScrapedMandate:
    term: str = ""
    start: str = ""
    end: str = ""
    constituency: str = ""
    club: str = ""


@dataclass
class ScrapedDeputy:
    sycomore_id: str
    url: str
    pa_id: str
    full_name: str
    birth_date: str = ""
    birth_place: str = ""
    mandates: list[ScrapedMandate] = field(default_factory=list)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def clean(value: Any) -> str:
    """Return a CSV-safe scalar, treating XML nil dictionaries as empty."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if value.get("@xsi:nil") == "true":
            return ""
        if "#text" in value:
            return clean(value["#text"])
        return ""
    text = html.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def actor_id(actor: dict[str, Any]) -> str:
    uid = actor.get("uid")
    if isinstance(uid, dict):
        return clean(uid.get("#text"))
    return clean(uid)


def parse_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def intervals_overlap(
    start_a: Any,
    end_a: Any,
    start_b: Any,
    end_b: Any,
) -> bool:
    a_start = parse_date(start_a) or date.min
    a_end = parse_date(end_a) or date.max
    b_start = parse_date(start_b) or date.min
    b_end = parse_date(end_b) or date.max
    return a_start <= b_end and b_start <= a_end


def unique_join(values: list[str], sep: str = ";") -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = clean(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return sep.join(result)


def normalize_label(value: Any) -> str:
    text = clean(value).casefold()
    text = text.replace("’", "'").replace("œ", "oe")
    decomposed = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in decomposed if not unicodedata.combining(char))
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"^president du groupe\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_listish(value: Any) -> list[str]:
    text = clean(value)
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return [text]
    if isinstance(parsed, list):
        return [clean(item) for item in parsed]
    return [clean(parsed)]


def load_party_map(party_csv: Path | None) -> dict[str, str]:
    if party_csv is None or not party_csv.exists():
        return {}

    party_map: dict[str, str] = {}
    with party_csv.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            party_id = clean(row.get("party_id"))
            if not party_id:
                continue
            labels = [
                clean(row.get("name")),
                clean(row.get("acronym")),
                *parse_listish(row.get("source_political_groups")),
                *parse_listish(row.get("interjection_aliases")),
            ]
            for label in labels:
                normalized = normalize_label(label)
                if normalized:
                    party_map.setdefault(normalized, party_id)
    return party_map


def map_clubs_to_party_ids(club_labels: list[str], party_map: dict[str, str]) -> list[str]:
    party_ids: list[str] = []
    for label in club_labels:
        normalized = normalize_label(label)
        alias = LEGACY_CLUB_ALIASES.get(normalized)
        party_id = party_map.get(normalize_label(alias)) if alias else party_map.get(normalized)
        if party_id:
            party_ids.append(party_id)
    return party_ids


def final_party_ids(party_ids: list[str]) -> str:
    unique_ids = unique_join(party_ids).split(";") if party_ids else []
    if len(unique_ids) > 1 and "P010" in unique_ids:
        unique_ids = [party_id for party_id in unique_ids if party_id != "P010"]
    return unique_join(unique_ids)


def final_club_labels(club_labels: list[str]) -> str:
    labels = unique_join(club_labels).split(";") if club_labels else []
    if len(labels) > 1:
        labels = [
            label
            for label in labels
            if normalize_label(label) != "deputes n'appartenant a aucun groupe"
        ]
    return unique_join(labels)


def organ_label(organs: dict[str, dict[str, Any]], organ_ref: Any) -> str:
    ref = clean(organ_ref)
    organ = organs.get(ref, {})
    return (
        clean(organ.get("libelle"))
        or clean(organ.get("libelleAbrege"))
        or clean(organ.get("libelleAbrev"))
        or ref
    )


def load_organs(organs_dir: Path) -> dict[str, dict[str, Any]]:
    organs: dict[str, dict[str, Any]] = {}
    for path in sorted(organs_dir.glob("*.json")):
        data = load_json(path).get("organe", {})
        uid = clean(data.get("uid"))
        if uid:
            organs[uid] = data
    return organs


def get_mandats(actor: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        mandat
        for mandat in as_list(actor.get("mandats", {}).get("mandat"))
        if isinstance(mandat, dict)
    ]


def birth_place(info: dict[str, Any]) -> str:
    parts = [
        clean(info.get("villeNais")),
        clean(info.get("depNais")),
        clean(info.get("paysNais")),
    ]
    return unique_join([part for part in parts if part], sep=", ")


def constituency(mandate: dict[str, Any]) -> str:
    if "__constituency" in mandate:
        return clean(mandate.get("__constituency"))

    election = mandate.get("election") or {}
    lieu = election.get("lieu") or {}
    departement = clean(lieu.get("departement"))
    num_departement = clean(lieu.get("numDepartement"))
    if departement and num_departement:
        return f"{departement} ({num_departement})"
    label = unique_join([departement, num_departement], sep=" ")
    ref = clean(election.get("refCirconscription"))
    if label and ref:
        return f"{label} ({ref})"
    return label or ref


def source_url(mp_id: str) -> str:
    return f"https://www.assemblee-nationale.fr/dyn/deputes/{mp_id}"


def assembly_seniority_years(assembly_mandates: list[dict[str, Any]]) -> str:
    days = 0
    today = date.today()
    for mandate in assembly_mandates:
        start = parse_date((mandate.get("mandature") or {}).get("datePriseFonction"))
        start = start or parse_date(mandate.get("dateDebut"))
        if not start:
            continue
        end = parse_date(mandate.get("dateFin")) or today
        if end >= start:
            days += (end - start).days
    if not days:
        return ""
    return f"{days / 365.25:.2f}"


def actor_status(mandats: list[dict[str, Any]]) -> str:
    type_organes = [
        clean(mandat.get("typeOrgane"))
        for mandat in mandats
        if clean(mandat.get("typeOrgane"))
    ]
    priority = [
        "ASSEMBLEE",
        "SENAT",
        "GOUVERNEMENT",
        "MINISTERE",
        "PRESREP",
        "CONSTITU",
    ]
    for type_organe in priority:
        if type_organe in type_organes:
            return type_organe
    return unique_join(type_organes)


def min_date_text(values: list[Any]) -> str:
    dates = [parse_date(value) for value in values]
    dates = [value for value in dates if value is not None]
    return min(dates).isoformat() if dates else ""


def max_date_text(values: list[Any]) -> str:
    if any(not clean(value) for value in values):
        return ""
    dates = [parse_date(value) for value in values]
    dates = [value for value in dates if value is not None]
    return max(dates).isoformat() if dates else ""


def group_assembly_mandates(
    assembly_mandates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate mandate interruptions into one row per legislature.

    The target table uses mp_id + term as a key. Some deputies have several
    ASSEMBLEE mandates in the same legislature, usually because of an
    interruption. This function preserves the full covered date range while
    keeping that key unique.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for mandate in assembly_mandates:
        term = clean(mandate.get("legislature")) or clean(mandate.get("uid"))
        grouped.setdefault(term, []).append(mandate)

    rows: list[dict[str, Any]] = []
    for term, mandates in grouped.items():
        starts = [
            (mandate.get("mandature") or {}).get("datePriseFonction")
            or mandate.get("dateDebut")
            for mandate in mandates
        ]
        election_dates = [mandate.get("dateDebut") for mandate in mandates]
        ends = [mandate.get("dateFin") for mandate in mandates]
        constituencies = unique_join(
            [constituency(mandate) for mandate in mandates],
            sep=";",
        )

        row = dict(mandates[0])
        row["legislature"] = term
        row["dateDebut"] = min_date_text(election_dates)
        row["dateFin"] = max_date_text(ends)
        row["mandature"] = dict(row.get("mandature") or {})
        row["mandature"]["datePriseFonction"] = min_date_text(starts)
        row["__election_date"] = min_date_text(election_dates)
        row["__constituency"] = constituencies
        rows.append(row)

    rows.sort(
        key=lambda item: (
            clean(item.get("legislature")),
            clean((item.get("mandature") or {}).get("datePriseFonction")),
            clean(item.get("uid")),
        )
    )
    return rows


def related_mandates(
    mandats: list[dict[str, Any]],
    assembly_mandate: dict[str, Any],
    type_organe: str,
) -> list[dict[str, Any]]:
    term = clean(assembly_mandate.get("legislature"))
    start = (assembly_mandate.get("mandature") or {}).get("datePriseFonction")
    start = start or assembly_mandate.get("dateDebut")
    end = assembly_mandate.get("dateFin")

    related: list[dict[str, Any]] = []
    for mandat in mandats:
        if clean(mandat.get("typeOrgane")) != type_organe:
            continue
        mandat_term = clean(mandat.get("legislature"))
        if mandat_term and term and mandat_term != term:
            continue
        if intervals_overlap(start, end, mandat.get("dateDebut"), mandat.get("dateFin")):
            related.append(mandat)
    related.sort(key=lambda item: clean(item.get("dateDebut")))
    return related


def politician_row(
    actor: dict[str, Any],
    mandats: list[dict[str, Any]],
    assembly_mandates: list[dict[str, Any]],
    country_id: str,
) -> dict[str, str]:
    ident = actor.get("etatCivil", {}).get("ident", {})
    naissance = actor.get("etatCivil", {}).get("infoNaissance", {})
    profession = actor.get("profession", {})

    return {
        "mp_id": actor_id(actor),
        "first_name": clean(ident.get("prenom")),
        "last_name": clean(ident.get("nom")),
        "birth_date": clean(naissance.get("dateNais")),
        "birth_place": birth_place(naissance),
        "education_level": "",
        "school": "",
        "academic_title": "",
        "profession": clean(profession.get("libelleCourant")),
        "languages": "",
        "seniority": assembly_seniority_years(assembly_mandates),
        "status": actor_status(mandats),
        "country_id": country_id,
    }


def mandate_row(
    mp_id: str,
    mandats: list[dict[str, Any]],
    assembly_mandate: dict[str, Any],
    organs: dict[str, dict[str, Any]],
    party_map: dict[str, str],
    country_id: str,
) -> dict[str, str]:
    party_refs = [
        clean((mandat.get("organes") or {}).get("organeRef"))
        for mandat in related_mandates(mandats, assembly_mandate, "PARPOL")
    ]
    club_labels = [
        organ_label(organs, (mandat.get("organes") or {}).get("organeRef"))
        for mandat in related_mandates(mandats, assembly_mandate, "GP")
    ]
    mapped_party_ids = map_clubs_to_party_ids(club_labels, party_map)
    committee_labels = [
        organ_label(organs, (mandat.get("organes") or {}).get("organeRef"))
        for mandat in related_mandates(mandats, assembly_mandate, "COMPER")
    ]
    party_id = final_party_ids(mapped_party_ids if party_map else party_refs)
    if party_map and not party_id:
        party_id = UNKNOWN_PARTY_ID

    mandature = assembly_mandate.get("mandature") or {}
    mandate_start = clean(mandature.get("datePriseFonction")) or clean(
        assembly_mandate.get("dateDebut")
    )

    return {
        "mp_id": mp_id,
        "term": clean(assembly_mandate.get("legislature")),
        "party_id": party_id,
        "club": final_club_labels(club_labels),
        "list": "",
        "constituency": constituency(assembly_mandate),
        "committees": unique_join(committee_labels),
        "mandate_start": mandate_start,
        "mandate_end": clean(assembly_mandate.get("dateFin")),
        "election_date": clean(assembly_mandate.get("__election_date"))
        or clean(assembly_mandate.get("dateDebut")),
        "votes": "",
        "source_url": source_url(mp_id),
        "country_id": country_id,
    }


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


class LinkTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "li", "div", "h1", "h2", "h3", "dt", "dd", "br", "tr"}:
            self.parts.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_parts = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._href is not None:
            self._link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((clean("".join(self._link_parts)), self._href))
            self._href = None
            self._link_parts = []
        if tag in {"p", "li", "div", "h1", "h2", "h3", "dt", "dd", "tr"}:
            self.parts.append("\n")

    def lines(self) -> list[str]:
        return [clean(line) for line in "".join(self.parts).splitlines() if clean(line)]


def html_lines_and_links(page: str) -> tuple[list[str], list[tuple[str, str]]]:
    parser = LinkTextParser()
    parser.feed(page)
    return parser.lines(), parser.links


def title_from_html(page: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", page, flags=re.I | re.S)
    return clean(re.sub(r"<[^>]+>", " ", match.group(1))) if match else ""


def sycomore_id_from_url(url: str) -> str:
    match = re.search(r"/sycomore/fiche/(?:%28num_dept%29/)?(\d+)", urlparse(url).path)
    return match.group(1) if match else ""


def pa_id_from_links(links: list[tuple[str, str]]) -> str:
    for _, href in links:
        match = re.search(r"/fiches_id/(\d+)\.asp\b", href or "")
        if match:
            return f"PA{match.group(1)}"
        match = re.search(r"/dyn/deputes/(PA\d+)\b", href or "")
        if match:
            return match.group(1)
    return ""


def fetch(url: str, cache_dir: Path, delay: float, refresh_cache: bool) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.html"
    if cache_path.exists() and not refresh_cache:
        return cache_path.read_text(encoding="utf-8")
    if delay:
        time.sleep(delay)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 local-data-archive"})
    try:
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            content = response.read().decode(charset, errors="replace")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc
    cache_path.write_text(content, encoding="utf-8")
    return content


def extract_deputy_links(page: str, base_url: str) -> list[DeputyLink]:
    _, links = html_lines_and_links(page)
    result: list[DeputyLink] = []
    seen: set[str] = set()
    for label, href in links:
        if not href or "/sycomore/fiche" not in href or not label:
            continue
        url = urljoin(base_url, href)
        sycomore_id = sycomore_id_from_url(url)
        if sycomore_id and sycomore_id not in seen:
            seen.add(sycomore_id)
            result.append(DeputyLink(label, url, sycomore_id))
    return result


def extract_next_page_url(page: str, base_url: str) -> str:
    _, links = html_lines_and_links(page)
    for label, href in links:
        if href and normalize_label(label) in {"suivant »", "suivant", "page suivante"}:
            return urljoin(base_url, href)
    return ""


def collect_deputy_links(
    first_url: str, cache_dir: Path, delay: float, refresh_cache: bool
) -> list[DeputyLink]:
    result: list[DeputyLink] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    next_url = first_url
    while next_url and next_url not in seen_pages:
        seen_pages.add(next_url)
        page = fetch(next_url, cache_dir, delay, refresh_cache)
        for link in extract_deputy_links(page, next_url):
            if link.sycomore_id not in seen_ids:
                seen_ids.add(link.sycomore_id)
                result.append(link)
        next_url = extract_next_page_url(page, next_url)
    return result


def parse_french_date(value: str) -> str:
    match = re.search(r"(\d{1,2})(?:er)?\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", clean(value))
    if not match:
        return ""
    month = MONTHS.get(match.group(2).casefold())
    return date(int(match.group(3)), month, int(match.group(1))).isoformat() if month else ""


def parse_term(value: str) -> str:
    match = re.search(r"\b([IVXLCDM]+)e?\s+législature\b", clean(value), flags=re.I)
    if match:
        return str(ROMAN_TERMS.get(match.group(1).upper(), ""))
    match = re.search(r"\b(\d{1,2})e?\s+législature\b", clean(value), flags=re.I)
    return match.group(1) if match else ""


def inline_value(line: str, label: str) -> str:
    match = re.match(rf"^{re.escape(label)}\s*:\s*(.+)$", clean(line), flags=re.I)
    return clean(match.group(1)) if match else ""


def value_after(lines: list[str], index: int) -> str:
    labels = {"Régime politique", "Législature", "Mandat", "Département", "Groupe"}
    return next((candidate for candidate in lines[index + 1 : index + 4] if candidate not in labels), "")


def line_value(lines: list[str], index: int, label: str) -> str:
    return inline_value(lines[index], label) or value_after(lines, index)


def parse_period(value: str) -> tuple[str, str]:
    match = re.search(r"Du\s+(.+?)\s+au\s+(.+)$", clean(value), flags=re.I)
    if match:
        return parse_french_date(match.group(1)), parse_french_date(match.group(2))
    match = re.search(r"Depuis\s+le\s+(.+)$", clean(value), flags=re.I)
    return (parse_french_date(match.group(1)), "") if match else ("", "")


def parse_mandates(lines: list[str]) -> list[ScrapedMandate]:
    mandates: list[ScrapedMandate] = []
    current: dict[str, str] = {}
    for index, line in enumerate(lines):
        if line == "Législature" or inline_value(line, "Législature"):
            if current.get("term"):
                mandates.append(ScrapedMandate(**current))
                current = {}
            current["term"] = parse_term(line_value(lines, index, "Législature"))
        elif line == "Mandat" or inline_value(line, "Mandat"):
            current["start"], current["end"] = parse_period(line_value(lines, index, "Mandat"))
        elif line == "Département" or inline_value(line, "Département"):
            current["constituency"] = line_value(lines, index, "Département")
        elif line == "Groupe" or inline_value(line, "Groupe"):
            current["club"] = line_value(lines, index, "Groupe")
    if current:
        mandates.append(ScrapedMandate(**current))
    return [mandate for mandate in mandates if mandate.term]


def parse_birth(lines: list[str]) -> tuple[str, str]:
    for line in lines:
        match = re.search(r"N[ée]e?\s+le\s+(.+?)(?:\s+à\s+(.+))?$", line)
        if match:
            return parse_french_date(match.group(1)), clean(match.group(2))
    return "", ""


def parse_deputy(page: str, link: DeputyLink) -> ScrapedDeputy:
    lines, links = html_lines_and_links(page)
    birth_date, birth_place = parse_birth(lines)
    return ScrapedDeputy(
        sycomore_id=link.sycomore_id,
        url=link.url,
        pa_id=pa_id_from_links(links),
        full_name=title_from_html(page) or link.name,
        birth_date=birth_date,
        birth_place=birth_place,
        mandates=parse_mandates(lines),
    )


def local_rows(
    actors_dir: Path,
    organs_dir: Path,
    country_id: str,
    party_csv: Path | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    organs = load_organs(organs_dir)
    party_map = load_party_map(party_csv)
    politician_rows: list[dict[str, str]] = []
    mandate_rows: list[dict[str, str]] = []

    for path in sorted(actors_dir.glob("*.json")):
        actor = load_json(path).get("acteur", {})
        mp_id = actor_id(actor)
        if not mp_id:
            continue

        mandats = get_mandats(actor)
        assembly_mandates = [
            mandat for mandat in mandats if clean(mandat.get("typeOrgane")) == "ASSEMBLEE"
        ]
        assembly_mandates.sort(
            key=lambda item: (
                clean(item.get("legislature")),
                clean(item.get("dateDebut")),
                clean(item.get("uid")),
            )
        )

        politician_rows.append(politician_row(actor, mandats, assembly_mandates, country_id))
        for assembly_mandate in group_assembly_mandates(assembly_mandates):
            mandate_rows.append(
                mandate_row(mp_id, mandats, assembly_mandate, organs, party_map, country_id)
            )

    return politician_rows, mandate_rows, party_map


def normalize_name(value: str) -> str:
    text = re.sub(r"\bnee?\b.*$", "", normalize_label(value))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def split_name(full_name: str) -> tuple[str, str]:
    parts = re.sub(r"\s+N[ée]e?\s+.*$", "", clean(full_name), flags=re.I).split()
    return (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (clean(full_name), "")


def map_club_to_party_id(club: str, party_map: dict[str, str]) -> str:
    ids = map_clubs_to_party_ids(clean(club).split(";"), party_map)
    return final_party_ids(ids) or (UNKNOWN_PARTY_ID if party_map and clean(club) else "")


def scraped_politician_row(deputy: ScrapedDeputy, mp_id: str, country_id: str) -> dict[str, str]:
    first_name, last_name = split_name(deputy.full_name)
    return {
        "mp_id": mp_id,
        "first_name": first_name,
        "last_name": last_name,
        "birth_date": deputy.birth_date,
        "birth_place": deputy.birth_place,
        "education_level": "",
        "school": "",
        "academic_title": "",
        "profession": "",
        "languages": "",
        "seniority": "",
        "status": "ASSEMBLEE",
        "country_id": country_id,
    }


def scraped_mandate_row(
    mp_id: str, mandate: ScrapedMandate, deputy_url: str, party_map: dict[str, str], country_id: str
) -> dict[str, str]:
    return {
        "mp_id": mp_id,
        "term": mandate.term,
        "party_id": map_club_to_party_id(mandate.club, party_map),
        "club": mandate.club,
        "list": "",
        "constituency": mandate.constituency,
        "committees": "",
        "mandate_start": mandate.start,
        "mandate_end": mandate.end,
        "election_date": mandate.start,
        "votes": "",
        "source_url": deputy_url,
        "country_id": country_id,
    }


def politician_indexes(
    politicians: list[dict[str, str]],
) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    by_name_birth: dict[tuple[str, str], str] = {}
    names: dict[str, set[str]] = {}
    for row in politicians:
        mp_id = clean(row.get("mp_id"))
        name = normalize_name(f"{clean(row.get('first_name'))} {clean(row.get('last_name'))}")
        birth_date = clean(row.get("birth_date"))
        if mp_id and name:
            names.setdefault(name, set()).add(mp_id)
            if birth_date:
                by_name_birth.setdefault((name, birth_date), mp_id)
    return by_name_birth, {name: next(iter(ids)) for name, ids in names.items() if len(ids) == 1}


def migrate_mp_id(
    politicians: list[dict[str, str]], mandates: list[dict[str, str]], old_id: str, new_id: str
) -> None:
    if old_id == new_id:
        return
    for row in politicians:
        if clean(row.get("mp_id")) == old_id:
            row["mp_id"] = new_id
    for row in mandates:
        if clean(row.get("mp_id")) == old_id:
            row["mp_id"] = new_id


def generated_sycomore_pa_id(sycomore_id: str, used_ids: set[str]) -> str:
    """Build a deterministic PA-shaped fallback ID that cannot mask a real PA ID."""
    raw_id = clean(sycomore_id)
    digits = re.sub(r"\D+", "", raw_id)
    if digits:
        base = f"PA9{int(digits):06d}"
    else:
        digest = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()
        base = f"PA9{int(digest[:12], 16) % 1_000_000:06d}"

    candidate = base
    suffix = 1
    while candidate in used_ids:
        candidate = f"{base}{suffix:03d}"
        suffix += 1
    return candidate


def deduplicate_rows(
    politicians: list[dict[str, str]], mandates: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    reports = {"duplicate_politicians.csv": [], "duplicate_mandates.csv": []}
    unique_politicians: dict[str, dict[str, str]] = {}
    for row in politicians:
        mp_id = clean(row.get("mp_id"))
        if mp_id in unique_politicians:
            reports["duplicate_politicians.csv"].append(
                {"mp_id": mp_id, "kept_source": "local-first", "discarded_source": clean(row.get("source_url"))}
            )
            continue
        unique_politicians[mp_id] = row
    unique_mandates: dict[tuple[str, str], dict[str, str]] = {}
    for row in mandates:
        key = (clean(row.get("mp_id")), clean(row.get("term")))
        if key in unique_mandates:
            reports["duplicate_mandates.csv"].append(
                {
                    "mp_id": key[0],
                    "term": key[1],
                    "kept_source": clean(unique_mandates[key].get("source_url")),
                    "discarded_source": clean(row.get("source_url")),
                }
            )
            continue
        unique_mandates[key] = row
    return list(unique_politicians.values()), list(unique_mandates.values()), reports


def validate_rows(politicians: list[dict[str, str]], mandates: list[dict[str, str]]) -> None:
    politician_ids = [clean(row.get("mp_id")) for row in politicians]
    mandate_keys = [(clean(row.get("mp_id")), clean(row.get("term"))) for row in mandates]
    errors: list[str] = []
    if any(not mp_id for mp_id in politician_ids) or any(not mp_id for mp_id, _ in mandate_keys):
        errors.append("empty mp_id")
    if any(mp_id.startswith("SYC") for mp_id in politician_ids + [key[0] for key in mandate_keys]):
        errors.append("SYC identifier")
    if len(politician_ids) != len(set(politician_ids)):
        errors.append("duplicate politician mp_id")
    if len(mandate_keys) != len(set(mandate_keys)):
        errors.append("duplicate mandate mp_id + term")
    if set(mp_id for mp_id, _ in mandate_keys) - set(politician_ids):
        errors.append("mandate without politician")
    if errors:
        raise RuntimeError("Validation failed: " + ", ".join(errors))


def augment_from_sycomore(
    politicians: list[dict[str, str]],
    mandates: list[dict[str, str]],
    party_map: dict[str, str],
    terms: list[int],
    cache_dir: Path,
    delay: float,
    refresh_cache: bool,
    country_id: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    reports: dict[str, list[dict[str, str]]] = {
        "new_politicians.csv": [],
        "new_mandates.csv": [],
        "fallback_pa_ids.csv": [],
    }
    politician_ids = {clean(row.get("mp_id")) for row in politicians}
    mandate_keys = {(clean(row.get("mp_id")), clean(row.get("term"))) for row in mandates}
    by_name_birth, by_unique_name = politician_indexes(politicians)

    for term in terms:
        links = collect_deputy_links(SYCOMORE_LIST_URLS[term], cache_dir, delay, refresh_cache)
        print(f"Legislature {term}: {len(links)} Sycomore deputy links")
        for link in links:
            deputy = parse_deputy(fetch(link.url, cache_dir, delay, refresh_cache), link)
            name = normalize_name(deputy.full_name)
            matched_id = by_name_birth.get((name, deputy.birth_date)) or by_unique_name.get(name, "")
            if deputy.pa_id:
                mp_id = deputy.pa_id
            elif matched_id.startswith("PA"):
                mp_id = matched_id
            else:
                mp_id = generated_sycomore_pa_id(deputy.sycomore_id, politician_ids)
            old_id = matched_id or f"SYC{deputy.sycomore_id}"
            if old_id in politician_ids and old_id != mp_id:
                migrate_mp_id(politicians, mandates, old_id, mp_id)
                politician_ids.discard(old_id)
                politician_ids.add(mp_id)
                mandate_keys = {(mp_id if row_id == old_id else row_id, row_term) for row_id, row_term in mandate_keys}
                by_name_birth, by_unique_name = politician_indexes(politicians)
            if not deputy.pa_id and not matched_id:
                reports["fallback_pa_ids.csv"].append(
                    {"mp_id": mp_id, "sycomore_id": deputy.sycomore_id, "name": deputy.full_name, "source_url": deputy.url}
                )
            if mp_id not in politician_ids:
                row = scraped_politician_row(deputy, mp_id, country_id)
                politicians.append(row)
                reports["new_politicians.csv"].append(row)
                politician_ids.add(mp_id)
                by_name_birth, by_unique_name = politician_indexes(politicians)
            for scraped in deputy.mandates:
                if scraped.term != str(term) or (mp_id, scraped.term) in mandate_keys:
                    continue
                row = scraped_mandate_row(mp_id, scraped, deputy.url, party_map, country_id)
                mandates.append(row)
                reports["new_mandates.csv"].append(row)
                mandate_keys.add((mp_id, scraped.term))
    return politicians, mandates, reports


def write_reports(
    report_dir: Path,
    reports: dict[str, list[dict[str, str]]],
    politicians: list[dict[str, str]],
    mandates: list[dict[str, str]],
) -> None:
    reports["unresolved_party_ids.csv"] = [
        row for row in mandates if clean(row.get("party_id")) in {"", UNKNOWN_PARTY_ID}
    ]
    columns = {
        "new_politicians.csv": POLITICIAN_COLUMNS,
        "new_mandates.csv": MANDATE_COLUMNS,
        **REPORT_COLUMNS,
    }
    for filename, file_columns in columns.items():
        write_csv(report_dir / filename, file_columns, reports.get(filename, []))


def parse_terms(value: str) -> list[int]:
    terms = sorted({int(part.strip()) for part in value.split(",") if part.strip()})
    unknown = sorted(set(terms) - set(DEFAULT_TERMS))
    if unknown:
        raise argparse.ArgumentTypeError(f"unsupported legislature(s): {unknown}")
    return terms


def convert(args: argparse.Namespace) -> None:
    politicians, mandates, party_map = local_rows(
        args.actors_dir, args.organs_dir, args.country_id, args.party_csv
    )
    print(f"Local JSON: {len(politicians)} politicians and {len(mandates)} mandates")
    reports: dict[str, list[dict[str, str]]] = {
        "new_politicians.csv": [],
        "new_mandates.csv": [],
        "fallback_pa_ids.csv": [],
    }
    if not args.local_only:
        politicians, mandates, reports = augment_from_sycomore(
            politicians,
            mandates,
            party_map,
            args.terms,
            args.cache_dir,
            args.delay,
            args.refresh_cache,
            args.country_id,
        )
    for row in mandates:
        row["club"] = final_club_labels(clean(row.get("club")).split(";"))
        mapped = map_club_to_party_id(clean(row.get("club")), party_map)
        if clean(row.get("party_id")) in {"", UNKNOWN_PARTY_ID} and mapped:
            row["party_id"] = mapped
    politicians, mandates, duplicate_reports = deduplicate_rows(politicians, mandates)
    reports.update(duplicate_reports)
    validate_rows(politicians, mandates)
    unresolved = sum(1 for row in mandates if clean(row.get("party_id")) in {"", UNKNOWN_PARTY_ID})
    print(f"Final archive: {len(politicians)} politicians and {len(mandates)} mandates")
    print(f"Unresolved party_id rows: {unresolved}")
    if args.dry_run:
        print("Dry run: CSV files were not modified")
        return
    write_reports(args.report_dir, reports, politicians, mandates)
    write_csv(args.out_dir / "politician.csv", POLITICIAN_COLUMNS, politicians)
    write_csv(args.out_dir / "mandate.csv", MANDATE_COLUMNS, mandates)
    print(f"Wrote {args.out_dir / 'politician.csv'}")
    print(f"Wrote {args.out_dir / 'mandate.csv'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actors-dir", default=Path("data/deputes/acteur"), type=Path)
    parser.add_argument("--organs-dir", default=Path("data/deputes/organe"), type=Path)
    parser.add_argument("--out-dir", default=Path("data/output"), type=Path)
    parser.add_argument("--country-id", default="3")
    parser.add_argument(
        "--party-csv",
        default=Path("data/parties/party.csv"),
        type=Path,
        help="CSV used to map mandate.club labels to imported party_id values",
    )
    parser.add_argument("--terms", default=",".join(str(term) for term in DEFAULT_TERMS), type=parse_terms)
    parser.add_argument("--cache-dir", default=Path("deputes_boostrap/.sycomore_cache"), type=Path)
    parser.add_argument("--delay", default=0.15, type=float)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--local-only", action="store_true", help="Skip Sycomore scraping.")
    parser.add_argument("--report-dir", default=Path("deputes_boostrap/report"), type=Path)
    args = parser.parse_args()
    convert(args)


if __name__ == "__main__":
    main()
