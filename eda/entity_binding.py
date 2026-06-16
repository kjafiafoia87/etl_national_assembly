"""Bind speech rows to party and politician reference tables."""

from __future__ import annotations

import ast
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import pandas as pd


LEGACY_PARTY_ALIASES = {
    # Historical archive labels not present verbatim in party.csv.
    "ps": "SOC",
    "rpr": "R-UMP",
    "pcf": "GDR",
    "rcv": "RRDP",
}

PRESIDENT_SPEAKER_KEYS = {
    "president",
    "le president",
    "la presidente",
    "monsieur le president",
    "madame la presidente",
}

OPEN_MANDATE_END = pd.Timestamp("2099-12-31")

DEFAULT_SPEAKER_MP_ID_ALIASES = {
    "Francois Brottes": "PA680",
    "Daniel Fasquelle": "PA334149",
    "Emmanuel Tache de la Pagerie": "PA793382",
    "Lionel Tardy": "PA335159",
    "Audrey Dufeu Schubert": "PA720046",
}

SPEAKER_MARKER_RE = re.compile(
    r"^\s*(?:M\.|Mme|Mmes|MM\.|Mlle|Monsieur|Madame)\s+"
    r"[A-ZÀ-ÖØ-Þ][^.!?\n]{2,90}[,.]"
)


def normalize_key(value: Any) -> str:
    if pd.isna(value):
        return ""

    text = str(value).replace("’", "'").casefold()
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_person_key(value: Any) -> str:
    """Normalize a speaker/person name while dropping common French titles."""
    key = normalize_key(value)
    if not key:
        return ""

    tokens = key.split()
    while tokens and tokens[0] in {
        "m",
        "mr",
        "mme",
        "mlle",
        "monsieur",
        "madame",
        "mademoiselle",
    }:
        tokens.pop(0)
    return " ".join(tokens)


def extract_mp_ids_from_speaker_link(value: Any) -> list[str]:
    """Extract Assembly PA ids from old fiche links or already-normalized ids."""
    if pd.isna(value) or not str(value).strip():
        return []

    text = str(value)
    ids = {match.upper() for match in re.findall(r"\bPA\d+\b", text, flags=re.IGNORECASE)}
    ids.update(f"PA{match}" for match in re.findall(r"(\d+)\.asp\b", text))
    return sorted(ids)


def extract_date_from_text(value: Any) -> pd.Timestamp | pd.NaT:
    if pd.isna(value) or not str(value).strip():
        return pd.NaT

    text = str(value)
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)", text)
    if not match:
        return pd.NaT
    return pd.to_datetime(
        f"{match.group(1)}-{match.group(2)}-{match.group(3)}", errors="coerce"
    )


def name_similarity(left: Any, right: Any) -> float:
    left_key = normalize_person_key(left)
    right_key = normalize_person_key(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def normalize_manual_speaker_aliases(aliases: dict[str, str] | None) -> dict[str, str]:
    if not aliases:
        return {}
    return {
        normalize_person_key(speaker): str(mp_id).strip()
        for speaker, mp_id in aliases.items()
        if normalize_person_key(speaker) and str(mp_id).strip()
    }


def text_value(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def text_starts_with_speaker_marker(value: Any) -> bool:
    return bool(SPEAKER_MARKER_RE.match(text_value(value)))


def parse_listish(value: Any) -> list[str]:
    if pd.isna(value) or not str(value).strip():
        return []

    text = str(value).strip()
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return [text]

    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [str(parsed).strip()]


def build_party_lookup(party: pd.DataFrame) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for _, row in party.iterrows():
        party_id = row.get("party_id")
        if pd.isna(party_id) or not str(party_id).strip():
            continue

        labels = [
            row.get("party_id"),
            row.get("acronym"),
            row.get("name"),
            *parse_listish(row.get("source_political_groups")),
            *parse_listish(row.get("interjection_aliases")),
        ]
        record = row.to_dict()
        for label in labels:
            key = normalize_key(label)
            if key:
                lookup.setdefault(key, record)

    for source, target in LEGACY_PARTY_ALIASES.items():
        target_record = lookup.get(normalize_key(target))
        if target_record is not None:
            lookup[normalize_key(source)] = target_record

    return lookup


def bind_parties(
    frame: pd.DataFrame,
    party: pd.DataFrame,
    group_col: str = "parliamentary_group",
    party_col: str = "party",
) -> pd.DataFrame:
    """Bind rows to party.csv using parliamentary_group first, then party."""
    lookup = build_party_lookup(party)
    output = frame.copy()

    def source_value(row: pd.Series) -> tuple[Any, str | None]:
        group = row.get(group_col)
        if not pd.isna(group) and str(group).strip():
            return group, group_col
        source_party = row.get(party_col)
        if not pd.isna(source_party) and str(source_party).strip():
            return source_party, party_col
        return None, None

    sources = output.apply(source_value, axis=1)
    output["party_source_label"] = [value for value, _ in sources]
    output["party_source_column"] = [column for _, column in sources]

    records = [
        lookup.get(normalize_key(value)) if value is not None else None
        for value in output["party_source_label"]
    ]
    output["party_id"] = [record.get("party_id") if record else pd.NA for record in records]
    output["party_acronym"] = [
        record.get("acronym") if record else pd.NA for record in records
    ]
    output["party_name"] = [record.get("name") if record else pd.NA for record in records]
    output["party_bind_status"] = [
        "matched" if record else ("missing_source" if value is None else "unmatched")
        for record, value in zip(records, output["party_source_label"])
    ]
    return output


def build_politician_lookup(deputes: pd.DataFrame) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for _, row in deputes.iterrows():
        full_name = f"{row.get('first_name', '')} {row.get('last_name', '')}"
        key = normalize_key(full_name)
        if key:
            lookup.setdefault(key, row.to_dict())
    return lookup


def _resolve_link_col(frame: pd.DataFrame, link_col: str | None) -> str | None:
    if link_col is not None:
        return link_col
    for candidate in ("link_speaker", "speaker_link"):
        if candidate in frame.columns:
            return candidate
    return None


def _resolve_source_file_col(frame: pd.DataFrame, source_file_col: str | None) -> str | None:
    if source_file_col is not None:
        return source_file_col
    if "source_files" in frame.columns:
        return "source_files"
    return None


def _prepare_politicians(deputes: pd.DataFrame) -> pd.DataFrame:
    required_depute_cols = {"mp_id", "first_name", "last_name"}
    missing_depute_cols = required_depute_cols - set(deputes.columns)
    if missing_depute_cols:
        raise KeyError(f"Missing politician columns: {sorted(missing_depute_cols)}")

    people_cols = ["mp_id", "first_name", "last_name"]
    if "status" in deputes.columns:
        people_cols.append("status")
    people = deputes[people_cols].copy()
    people["mp_id"] = people["mp_id"].astype(str).str.strip()
    people["politician_full_name"] = (
        people["first_name"].fillna("").astype(str).str.strip()
        + " "
        + people["last_name"].fillna("").astype(str).str.strip()
    ).str.strip()
    people["_person_key"] = people["politician_full_name"].map(normalize_person_key)
    people["_last_key"] = people["_person_key"].str.split().str[-1].fillna("")
    if "status" in people.columns:
        people = people.rename(columns={"status": "politician_status"})
    else:
        people["politician_status"] = pd.NA
    return people[people["mp_id"].ne("") & people["_person_key"].ne("")].copy()


def _prepare_politician_mandates(
    deputes: pd.DataFrame,
    mandates: pd.DataFrame,
) -> pd.DataFrame:
    required_mandate_cols = {"mp_id", "mandate_start", "mandate_end"}
    missing_mandate_cols = required_mandate_cols - set(mandates.columns)
    if missing_mandate_cols:
        raise KeyError(f"Missing mandate columns: {sorted(missing_mandate_cols)}")

    people = _prepare_politicians(deputes)

    mandate_cols = ["mp_id", "mandate_start", "mandate_end"]
    if "term" in mandates.columns:
        mandate_cols.append("term")

    mandate_frame = mandates[mandate_cols].copy()
    mandate_frame["mp_id"] = mandate_frame["mp_id"].astype(str).str.strip()
    mandate_frame["_mandate_start"] = pd.to_datetime(
        mandate_frame["mandate_start"], errors="coerce"
    )
    mandate_frame["_mandate_end"] = pd.to_datetime(
        mandate_frame["mandate_end"], errors="coerce"
    ).fillna(OPEN_MANDATE_END)

    politician_mandates = mandate_frame.merge(people, on="mp_id", how="inner")
    politician_mandates = politician_mandates[
        politician_mandates["mp_id"].ne("")
        & politician_mandates["_person_key"].ne("")
        & politician_mandates["_mandate_start"].notna()
    ].copy()
    return politician_mandates.drop_duplicates()


def _pick_best_candidate(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates

    sort_cols = ["_row_id", "_score", "_mandate_start", "_mandate_end"]
    ascending = [True, False, False, False]
    return (
        candidates.sort_values(sort_cols, ascending=ascending)
        .drop_duplicates("_row_id", keep="first")
        .copy()
    )


def _active_candidate_rows(candidates: pd.DataFrame) -> pd.DataFrame:
    return candidates[
        candidates["_speech_date"].notna()
        & candidates["_mandate_start"].le(candidates["_speech_date"])
        & candidates["_mandate_end"].ge(candidates["_speech_date"])
    ].copy()


def _candidate_output_columns(
    candidates: pd.DataFrame,
    method: str,
    status: str = "matched",
) -> pd.DataFrame:
    output_cols = [
        "_row_id",
        "mp_id",
        "first_name",
        "last_name",
        "_score",
        "mandate_start",
        "mandate_end",
        "politician_status",
    ]
    optional_cols = [col for col in ["term"] if col in candidates.columns]
    selected = candidates[output_cols + optional_cols].copy()
    selected["politician_bind_status"] = status
    selected["politician_bind_method"] = method
    return selected


def bind_politicians_with_mandates(
    frame: pd.DataFrame,
    deputes: pd.DataFrame,
    mandates: pd.DataFrame,
    speaker_col: str = "speaker",
    link_col: str | None = None,
    date_col: str = "date",
    source_file_col: str | None = None,
    target_col: str = "mp_id",
    min_link_score: float = 0.80,
    min_name_score: float = 0.92,
    exclude_presidents: bool = True,
    allow_inactive_mandate_fallback: bool = True,
    manual_speaker_mp_ids: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Bind speech speakers to politician ids with link/name/date mandate checks.

    Priority:
    1. Extract PA ids from link_speaker/speaker_link, then confirm name and active mandate.
    2. If no valid link match, bind by exact normalized speaker name and active mandate.
    3. If still unmatched, fuzzy-match within the same normalized last-name block and mandate.
    4. Optionally bind unique link/name matches without active parliamentary mandate.
    """
    if speaker_col not in frame.columns:
        raise KeyError(f"Missing speaker column: {speaker_col!r}")
    if date_col not in frame.columns:
        raise KeyError(f"Missing date column: {date_col!r}")

    resolved_link_col = _resolve_link_col(frame, link_col)
    resolved_source_file_col = _resolve_source_file_col(frame, source_file_col)
    manual_aliases = normalize_manual_speaker_aliases(DEFAULT_SPEAKER_MP_ID_ALIASES)
    manual_aliases.update(normalize_manual_speaker_aliases(manual_speaker_mp_ids))
    politicians = _prepare_politicians(deputes)
    politician_mandates = _prepare_politician_mandates(deputes, mandates)

    output = frame.copy()
    output[target_col] = pd.NA
    output["politician_first_name"] = pd.NA
    output["politician_last_name"] = pd.NA
    output["politician_status"] = pd.NA
    output["politician_name_score"] = pd.NA
    output["politician_bind_status"] = "unmatched"
    output["politician_bind_method"] = pd.NA
    output["politician_mandate_start"] = pd.NA
    output["politician_mandate_end"] = pd.NA
    output["politician_date_source"] = pd.NA
    if "term" in politician_mandates.columns:
        output["politician_term"] = pd.NA

    meta_cols = [speaker_col, date_col]
    if resolved_link_col is not None:
        meta_cols.append(resolved_link_col)
    if resolved_source_file_col is not None and resolved_source_file_col not in meta_cols:
        meta_cols.append(resolved_source_file_col)

    meta = output[meta_cols].copy()
    meta["_row_id"] = output.index
    meta["_speaker_key"] = meta[speaker_col].map(normalize_person_key)
    meta["_speaker_last_key"] = meta["_speaker_key"].str.split().str[-1].fillna("")
    meta["_speech_date"] = pd.to_datetime(meta[date_col], errors="coerce", dayfirst=True)
    meta["_date_source"] = pd.NA
    meta.loc[meta["_speech_date"].notna(), "_date_source"] = date_col
    if resolved_source_file_col is not None:
        source_dates = meta[resolved_source_file_col].map(extract_date_from_text)
        fill_from_source = meta["_speech_date"].isna() & source_dates.notna()
        meta.loc[fill_from_source, "_speech_date"] = source_dates.loc[fill_from_source]
        meta.loc[fill_from_source, "_date_source"] = resolved_source_file_col
    meta["_is_president"] = meta["_speaker_key"].isin(PRESIDENT_SPEAKER_KEYS)
    meta["_has_speaker"] = meta["_speaker_key"].ne("")
    meta["_has_date"] = meta["_speech_date"].notna()
    output["politician_date_source"] = meta["_date_source"].to_numpy()

    if resolved_link_col is not None:
        meta["_speaker_link_mp_ids"] = meta[resolved_link_col].map(
            extract_mp_ids_from_speaker_link
        )
        output["speaker_link_mp_ids"] = meta["_speaker_link_mp_ids"].map(
            lambda values: ";".join(values) if values else pd.NA
        )
        known_ids = set(politicians["mp_id"])
        output["speaker_link_mp_id_exists"] = meta["_speaker_link_mp_ids"].map(
            lambda values: any(value in known_ids for value in values)
        )

    output.loc[~meta["_has_speaker"], "politician_bind_status"] = "missing_speaker"
    output.loc[meta["_has_speaker"] & ~meta["_has_date"], "politician_bind_status"] = (
        "missing_date"
    )
    if exclude_presidents:
        output.loc[meta["_is_president"], "politician_bind_status"] = "president"

    eligible = meta["_has_speaker"] & meta["_has_date"]
    if exclude_presidents:
        eligible &= ~meta["_is_president"]

    matches: list[pd.DataFrame] = []
    matched_row_ids: set[Any] = set()

    if resolved_link_col is not None:
        link_meta = meta.loc[eligible & meta["_speaker_link_mp_ids"].map(bool)].copy()
        if not link_meta.empty:
            link_candidates = link_meta.explode("_speaker_link_mp_ids").rename(
                columns={"_speaker_link_mp_ids": "candidate_mp_id"}
            )
            link_candidates = link_candidates.merge(
                politician_mandates,
                left_on="candidate_mp_id",
                right_on="mp_id",
                how="inner",
            )
            link_candidates = _active_candidate_rows(link_candidates)
            if not link_candidates.empty:
                link_candidates["_score"] = [
                    name_similarity(speaker, full_name)
                    for speaker, full_name in zip(
                        link_candidates[speaker_col],
                        link_candidates["politician_full_name"],
                    )
                ]
                link_candidates = link_candidates[
                    link_candidates["_score"].ge(min_link_score)
                ]
                link_matches = _pick_best_candidate(link_candidates)
                if not link_matches.empty:
                    matched_row_ids.update(link_matches["_row_id"])
                    matches.append(
                        _candidate_output_columns(link_matches, "link_name_mandate")
                    )

    remaining = eligible & ~meta["_row_id"].isin(matched_row_ids)
    manual_meta = meta.loc[remaining & meta["_speaker_key"].isin(manual_aliases)].copy()
    if not manual_meta.empty:
        manual_meta["candidate_mp_id"] = manual_meta["_speaker_key"].map(manual_aliases)
        manual_candidates = manual_meta.merge(
            politician_mandates,
            left_on="candidate_mp_id",
            right_on="mp_id",
            how="inner",
        )
        manual_candidates = _active_candidate_rows(manual_candidates)
        if not manual_candidates.empty:
            manual_candidates["_score"] = 1.0
            manual_matches = _pick_best_candidate(manual_candidates)
            if not manual_matches.empty:
                matched_row_ids.update(manual_matches["_row_id"])
                matches.append(
                    _candidate_output_columns(manual_matches, "manual_alias_mandate")
                )

    remaining = eligible & ~meta["_row_id"].isin(matched_row_ids)
    exact_meta = meta.loc[remaining].copy()
    if not exact_meta.empty:
        exact_candidates = exact_meta.merge(
            politician_mandates,
            left_on="_speaker_key",
            right_on="_person_key",
            how="inner",
        )
        exact_candidates = _active_candidate_rows(exact_candidates)
        if not exact_candidates.empty:
            exact_candidates["_score"] = 1.0
            exact_matches = _pick_best_candidate(exact_candidates)
            if not exact_matches.empty:
                matched_row_ids.update(exact_matches["_row_id"])
                matches.append(
                    _candidate_output_columns(exact_matches, "name_exact_mandate")
                )

    remaining = eligible & ~meta["_row_id"].isin(matched_row_ids)
    fuzzy_meta = meta.loc[remaining & meta["_speaker_last_key"].ne("")].copy()
    if not fuzzy_meta.empty:
        fuzzy_candidates = fuzzy_meta.merge(
            politician_mandates,
            left_on="_speaker_last_key",
            right_on="_last_key",
            how="inner",
        )
        fuzzy_candidates = _active_candidate_rows(fuzzy_candidates)
        if not fuzzy_candidates.empty:
            fuzzy_candidates["_score"] = [
                name_similarity(speaker, full_name)
                for speaker, full_name in zip(
                    fuzzy_candidates[speaker_col],
                    fuzzy_candidates["politician_full_name"],
                )
            ]
            fuzzy_candidates = fuzzy_candidates[
                fuzzy_candidates["_score"].ge(min_name_score)
            ]
            fuzzy_matches = _pick_best_candidate(fuzzy_candidates)
            if not fuzzy_matches.empty:
                matched_row_ids.update(fuzzy_matches["_row_id"])
                matches.append(
                    _candidate_output_columns(fuzzy_matches, "name_fuzzy_mandate")
                )

    if allow_inactive_mandate_fallback:
        remaining = eligible & ~meta["_row_id"].isin(matched_row_ids)
        if resolved_link_col is not None:
            link_meta = meta.loc[remaining & meta["_speaker_link_mp_ids"].map(bool)].copy()
            if not link_meta.empty:
                inactive_link_candidates = link_meta.explode(
                    "_speaker_link_mp_ids"
                ).rename(columns={"_speaker_link_mp_ids": "candidate_mp_id"})
                inactive_link_candidates = inactive_link_candidates.merge(
                    politicians,
                    left_on="candidate_mp_id",
                    right_on="mp_id",
                    how="inner",
                )
                if not inactive_link_candidates.empty:
                    inactive_link_candidates["_score"] = [
                        name_similarity(speaker, full_name)
                        for speaker, full_name in zip(
                            inactive_link_candidates[speaker_col],
                            inactive_link_candidates["politician_full_name"],
                        )
                    ]
                    inactive_link_candidates = inactive_link_candidates[
                        inactive_link_candidates["_score"].ge(min_link_score)
                    ].copy()
                    if not inactive_link_candidates.empty:
                        inactive_link_candidates["mandate_start"] = pd.NA
                        inactive_link_candidates["mandate_end"] = pd.NA
                        inactive_link_matches = (
                            inactive_link_candidates.sort_values(
                                ["_row_id", "_score"], ascending=[True, False]
                            )
                            .drop_duplicates("_row_id", keep="first")
                            .copy()
                        )
                        matched_row_ids.update(inactive_link_matches["_row_id"])
                        matches.append(
                            _candidate_output_columns(
                                inactive_link_matches,
                                "link_name_no_active_mandate",
                                status="matched_no_active_mandate",
                            )
                        )

        remaining = eligible & ~meta["_row_id"].isin(matched_row_ids)
        manual_meta = meta.loc[
            remaining & meta["_speaker_key"].isin(manual_aliases)
        ].copy()
        if not manual_meta.empty:
            manual_meta["candidate_mp_id"] = manual_meta["_speaker_key"].map(
                manual_aliases
            )
            inactive_manual_candidates = manual_meta.merge(
                politicians,
                left_on="candidate_mp_id",
                right_on="mp_id",
                how="inner",
            )
            if not inactive_manual_candidates.empty:
                inactive_manual_candidates["_score"] = 1.0
                inactive_manual_candidates["mandate_start"] = pd.NA
                inactive_manual_candidates["mandate_end"] = pd.NA
                inactive_manual_matches = inactive_manual_candidates.drop_duplicates(
                    "_row_id", keep="first"
                ).copy()
                matched_row_ids.update(inactive_manual_matches["_row_id"])
                matches.append(
                    _candidate_output_columns(
                        inactive_manual_matches,
                        "manual_alias_no_active_mandate",
                        status="matched_no_active_mandate",
                    )
                )

        remaining = eligible & ~meta["_row_id"].isin(matched_row_ids)
        exact_meta = meta.loc[remaining].copy()
        if not exact_meta.empty:
            unique_name_politicians = politicians[
                ~politicians["_person_key"].duplicated(keep=False)
            ].copy()
            inactive_exact_candidates = exact_meta.merge(
                unique_name_politicians,
                left_on="_speaker_key",
                right_on="_person_key",
                how="inner",
            )
            if not inactive_exact_candidates.empty:
                inactive_exact_candidates["_score"] = 1.0
                inactive_exact_candidates["mandate_start"] = pd.NA
                inactive_exact_candidates["mandate_end"] = pd.NA
                inactive_exact_matches = inactive_exact_candidates.drop_duplicates(
                    "_row_id", keep="first"
                ).copy()
                matched_row_ids.update(inactive_exact_matches["_row_id"])
                matches.append(
                    _candidate_output_columns(
                        inactive_exact_matches,
                        "name_exact_no_active_mandate",
                        status="matched_no_active_mandate",
                    )
                )

    if matches:
        all_matches = pd.concat(matches, ignore_index=True)
        all_matches = all_matches.drop_duplicates("_row_id", keep="first")
        row_ids = all_matches["_row_id"]
        output.loc[row_ids, target_col] = all_matches["mp_id"].to_numpy()
        output.loc[row_ids, "politician_first_name"] = all_matches[
            "first_name"
        ].to_numpy()
        output.loc[row_ids, "politician_last_name"] = all_matches[
            "last_name"
        ].to_numpy()
        output.loc[row_ids, "politician_status"] = all_matches[
            "politician_status"
        ].to_numpy()
        output.loc[row_ids, "politician_name_score"] = all_matches["_score"].to_numpy()
        output.loc[row_ids, "politician_bind_status"] = all_matches[
            "politician_bind_status"
        ].to_numpy()
        output.loc[row_ids, "politician_bind_method"] = all_matches[
            "politician_bind_method"
        ].to_numpy()
        output.loc[row_ids, "politician_mandate_start"] = all_matches[
            "mandate_start"
        ].to_numpy()
        output.loc[row_ids, "politician_mandate_end"] = all_matches[
            "mandate_end"
        ].to_numpy()
        if "term" in all_matches.columns:
            output.loc[row_ids, "politician_term"] = all_matches["term"].to_numpy()

    return output


def bind_politicians(
    frame: pd.DataFrame,
    deputes: pd.DataFrame,
    speaker_col: str = "speaker",
) -> pd.DataFrame:
    """Bind rows to politician.csv by normalized speaker full name."""
    lookup = build_politician_lookup(deputes)
    output = frame.copy()

    records = []
    statuses = []
    for speaker in output.get(speaker_col, pd.Series(index=output.index, dtype=object)):
        if pd.isna(speaker) or not str(speaker).strip():
            records.append(None)
            statuses.append("missing_source")
            continue

        record = lookup.get(normalize_key(speaker))
        records.append(record)
        statuses.append("matched" if record else "unmatched")

    output["mp_id"] = [record.get("mp_id") if record else pd.NA for record in records]
    output["politician_first_name"] = [
        record.get("first_name") if record else pd.NA for record in records
    ]
    output["politician_last_name"] = [
        record.get("last_name") if record else pd.NA for record in records
    ]
    output["politician_bind_status"] = statuses
    return output


def merge_missing_speaker_rows(
    frame: pd.DataFrame,
    text_cols: tuple[str, ...] = ("text_speech_clean", "text_speech_brut"),
    status_col: str = "politician_bind_status",
    missing_status: str = "missing_speaker",
    speaker_col: str = "speaker",
    id_col: str = "id",
    boundary_cols: tuple[str, ...] = ("source_files", "date", "numSeance"),
    text_separator: str = "\n\n",
    guard_speaker_marker: bool = True,
    max_audit_rows: int | None = 10_000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Absorb chronologically contiguous missing-speaker text into the prior speaker.

    Returns the compacted frame and an audit table. Rows blocked by a boundary
    mismatch or speaker-looking text are kept unchanged.
    """
    if status_col not in frame.columns:
        raise KeyError(f"Missing status column: {status_col!r}")
    if speaker_col not in frame.columns:
        raise KeyError(f"Missing speaker column: {speaker_col!r}")

    merge_text_cols = tuple(col for col in text_cols if col in frame.columns)
    if not merge_text_cols:
        raise KeyError(f"None of the text columns exist: {text_cols!r}")

    output = frame.copy()
    output["merged_missing_speaker_rows"] = 0
    output["merged_missing_speaker_ids"] = pd.NA

    available_boundary_cols = tuple(col for col in boundary_cols if col in output.columns)

    row_count = len(output)
    positions = np.arange(row_count)
    missing_mask = output[status_col].eq(missing_status).to_numpy()
    speaker_present = output[speaker_col].map(text_value).ne("").to_numpy()
    anchor_positions = pd.Series(
        np.where(~missing_mask & speaker_present, positions, np.nan)
    ).ffill()

    missing_positions = np.flatnonzero(missing_mask)
    if len(missing_positions) == 0:
        return output.copy(), pd.DataFrame()

    target_positions_float = anchor_positions.iloc[missing_positions].to_numpy()
    has_target = ~pd.isna(target_positions_float)
    target_positions = np.full(len(missing_positions), -1, dtype=int)
    target_positions[has_target] = target_positions_float[has_target].astype(int)

    statuses = np.full(len(missing_positions), "merged", dtype=object)
    statuses[~has_target] = "blocked_no_previous_speaker"

    if available_boundary_cols:
        boundary_ok = np.ones(len(missing_positions), dtype=bool)
        valid_target_rows = has_target.copy()
        for col in available_boundary_cols:
            values = output[col].where(output[col].notna(), "__NA__").astype(str).to_numpy()
            source_values = values[missing_positions[valid_target_rows]]
            target_values = values[target_positions[valid_target_rows]]
            col_ok = source_values == target_values
            valid_indices = np.flatnonzero(valid_target_rows)
            boundary_ok[valid_indices] &= col_ok
        statuses[has_target & ~boundary_ok] = "blocked_boundary_mismatch"

    if guard_speaker_marker:
        starts_with_speaker = np.zeros(len(missing_positions), dtype=bool)
        for col in merge_text_cols:
            col_starts = (
                output[col]
                .map(text_starts_with_speaker_marker)
                .iloc[missing_positions]
                .to_numpy()
            )
            starts_with_speaker |= col_starts
        statuses[
            has_target
            & (statuses == "merged")
            & starts_with_speaker
        ] = "blocked_text_starts_with_speaker_marker"

    merged_mask = statuses == "merged"
    merged_source_positions = missing_positions[merged_mask]
    merged_target_positions = target_positions[merged_mask]
    separator_totals: dict[str, int] = {}
    for col in merge_text_cols:
        source_texts_for_check = output.iloc[missing_positions][col].map(text_value)
        target_texts_for_check = pd.Series(
            [
                text_value(output.iloc[pos][col]) if pos >= 0 else ""
                for pos in target_positions
            ]
        )
        separator_totals[col] = int(
            np.where(
                merged_mask
                & source_texts_for_check.ne("").to_numpy()
                & target_texts_for_check.ne("").to_numpy(),
                len(text_separator),
                0,
            ).sum()
        )

    keep_mask = np.ones(row_count, dtype=bool)
    keep_mask[merged_source_positions] = False

    pairs = pd.DataFrame(
        {
            "source_pos": merged_source_positions,
            "target_pos": merged_target_positions,
        }
    )

    if not pairs.empty:
        for col in merge_text_cols:
            source_texts = output.iloc[pairs["source_pos"]][col].map(text_value).to_numpy()
            text_pairs = pairs.assign(source_text=source_texts)
            text_pairs = text_pairs[text_pairs["source_text"].ne("")]
            if text_pairs.empty:
                continue
            additions = text_pairs.groupby("target_pos", sort=False)["source_text"].agg(
                lambda values: text_separator.join(values)
            )
            col_idx = output.columns.get_loc(col)
            for target_pos, addition in additions.items():
                target_text = text_value(output.iat[int(target_pos), col_idx])
                output.iat[int(target_pos), col_idx] = (
                    f"{target_text}{text_separator}{addition}"
                    if target_text
                    else addition
                )

        counts = pairs.groupby("target_pos", sort=False).size()
        count_col_idx = output.columns.get_loc("merged_missing_speaker_rows")
        for target_pos, count in counts.items():
            output.iat[int(target_pos), count_col_idx] = int(count)

        if id_col in output.columns:
            source_ids = output.iloc[pairs["source_pos"]][id_col].fillna("").astype(str).to_numpy()
        else:
            source_ids = output.index[pairs["source_pos"]].astype(str).to_numpy()
        id_pairs = pairs.assign(source_id=source_ids)
        merged_ids = id_pairs.groupby("target_pos", sort=False)["source_id"].agg(
            lambda values: ";".join(value for value in values if value)
        )
        ids_col_idx = output.columns.get_loc("merged_missing_speaker_ids")
        for target_pos, merged_ids_value in merged_ids.items():
            output.iat[int(target_pos), ids_col_idx] = merged_ids_value or pd.NA

    audit_row_positions = np.arange(len(missing_positions))
    if max_audit_rows is not None and len(audit_row_positions) > max_audit_rows:
        blocked_audit_positions = audit_row_positions[statuses != "merged"]
        merged_audit_positions = audit_row_positions[statuses == "merged"]
        blocked_keep = blocked_audit_positions[:max_audit_rows]
        remaining_slots = max_audit_rows - len(blocked_keep)
        merged_keep = (
            merged_audit_positions[:remaining_slots]
            if remaining_slots > 0
            else np.array([], dtype=int)
        )
        audit_row_positions = np.sort(np.concatenate([blocked_keep, merged_keep]))

    audit_missing_positions = missing_positions[audit_row_positions]
    audit_target_positions = target_positions[audit_row_positions]
    audit_statuses = statuses[audit_row_positions]

    audit = pd.DataFrame(
        {
            "source_index": output.index[audit_missing_positions],
            "target_index": [
                output.index[pos] if pos >= 0 else pd.NA for pos in audit_target_positions
            ],
            "status": audit_statuses,
        }
    )
    if id_col in output.columns:
        audit["source_id"] = output.iloc[audit_missing_positions][id_col].to_numpy()
        audit["target_id"] = [
            output.iloc[pos][id_col] if pos >= 0 else pd.NA
            for pos in audit_target_positions
        ]
    else:
        audit["source_id"] = audit["source_index"]
        audit["target_id"] = audit["target_index"]

    audit["target_speaker"] = [
        output.iloc[pos][speaker_col] if pos >= 0 else pd.NA
        for pos in audit_target_positions
    ]
    for col in available_boundary_cols:
        audit[f"source_{col}"] = output.iloc[audit_missing_positions][col].to_numpy()
        audit[f"target_{col}"] = [
            output.iloc[pos][col] if pos >= 0 else pd.NA
            for pos in audit_target_positions
        ]

    for col in merge_text_cols:
        source_texts = output.iloc[audit_missing_positions][col].map(text_value)
        source_chars = source_texts.map(len).to_numpy()
        target_texts = pd.Series(
            [
                text_value(output.iloc[pos][col]) if pos >= 0 else ""
                for pos in audit_target_positions
            ]
        )
        audit[f"{col}_chars"] = source_chars
        audit[f"{col}_separator_chars"] = np.where(
            (audit_statuses == "merged")
            & source_texts.ne("").to_numpy()
            & target_texts.ne("").to_numpy(),
            len(text_separator),
            0,
        )
        audit[f"{col}_preview"] = source_texts.str.slice(0, 240).to_numpy()

    compacted = output.iloc[keep_mask].copy()
    audit.attrs["total_missing_speaker_rows"] = int(len(missing_positions))
    audit.attrs["status_counts"] = pd.Series(statuses).value_counts().to_dict()
    audit.attrs["separator_totals"] = separator_totals
    audit.attrs["audit_rows_sampled"] = bool(len(audit_row_positions) < len(missing_positions))
    return compacted, audit


def politician_pairing_summary(
    frame: pd.DataFrame,
    target_col: str = "mp_id",
    status_col: str = "politician_bind_status",
    speaker_col: str = "speaker",
) -> pd.Series:
    speaker_keys = frame[speaker_col].map(normalize_person_key)
    is_president = speaker_keys.isin(PRESIDENT_SPEAKER_KEYS)
    is_missing_speaker = (
        frame[status_col].eq("missing_speaker")
        if status_col in frame.columns
        else speaker_keys.eq("")
    )
    matched = frame[target_col].notna()
    boundable = ~is_president & ~is_missing_speaker
    non_president = ~is_president

    return pd.Series(
        {
            "rows": len(frame),
            "rows_non_president": int(non_president.sum()),
            "rows_missing_speaker": int(is_missing_speaker.sum()),
            "rows_boundable_non_president": int(boundable.sum()),
            "rows_paired": int((boundable & matched).sum()),
            "rows_unpaired_boundable": int((boundable & ~matched).sum()),
            "pairing_rate_boundable_non_president": (
                float((boundable & matched).sum() / boundable.sum())
                if boundable.sum()
                else 0.0
            ),
            "pairing_rate_all_non_president": (
                float((non_president & matched).sum() / non_president.sum())
                if non_president.sum()
                else 0.0
            ),
        }
    )


def missing_speaker_merge_report(
    before: pd.DataFrame,
    after: pd.DataFrame,
    audit: pd.DataFrame,
    text_col: str = "text_speech_clean",
    target_col: str = "mp_id",
    status_col: str = "politician_bind_status",
    speaker_col: str = "speaker",
) -> pd.Series:
    before_stats = politician_pairing_summary(
        before, target_col=target_col, status_col=status_col, speaker_col=speaker_col
    )
    after_stats = politician_pairing_summary(
        after, target_col=target_col, status_col=status_col, speaker_col=speaker_col
    )

    before_chars = before[text_col].map(lambda value: len(text_value(value))).sum()
    after_chars = after[text_col].map(lambda value: len(text_value(value))).sum()
    separator_col = f"{text_col}_separator_chars"
    status_counts = audit.attrs.get("status_counts")
    if status_counts is None:
        status_counts = audit["status"].value_counts(dropna=False).to_dict() if not audit.empty else {}

    separator_totals = audit.attrs.get("separator_totals", {})
    expected_separator_chars = int(
        separator_totals.get(
            text_col,
            audit.loc[audit["status"].eq("merged"), separator_col].sum()
            if separator_col in audit.columns and not audit.empty
            else 0,
        )
    )

    absorbed_rows = int(status_counts.get("merged", 0))
    blocked_rows = int(sum(count for status, count in status_counts.items() if status != "merged"))
    risky_blocked_rows = int(status_counts.get("blocked_text_starts_with_speaker_marker", 0))

    return pd.Series(
        {
            "rows_before": int(before_stats["rows"]),
            "rows_after": int(after_stats["rows"]),
            "rows_absorbed": absorbed_rows,
            "missing_speaker_before": int(before_stats["rows_missing_speaker"]),
            "missing_speaker_after": int(after_stats["rows_missing_speaker"]),
            "blocked_missing_speaker_rows": blocked_rows,
            "blocked_speaker_marker_rows": risky_blocked_rows,
            "audit_rows_returned": int(len(audit)),
            "audit_rows_sampled": bool(audit.attrs.get("audit_rows_sampled", False)),
            "text_chars_before": int(before_chars),
            "text_chars_after": int(after_chars),
            "expected_separator_chars": expected_separator_chars,
            "text_char_check_pass": bool(after_chars == before_chars + expected_separator_chars),
            "pairing_rate_before": float(
                before_stats["pairing_rate_boundable_non_president"]
            ),
            "pairing_rate_after": float(
                after_stats["pairing_rate_boundable_non_president"]
            ),
            "pairing_rate_delta": float(
                after_stats["pairing_rate_boundable_non_president"]
                - before_stats["pairing_rate_boundable_non_president"]
            ),
        }
    )


def bind_entities(
    frame: pd.DataFrame,
    party: pd.DataFrame,
    deputes: pd.DataFrame,
) -> pd.DataFrame:
    return bind_politicians(bind_parties(frame, party), deputes)


def bind_report(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return compact success/failure reports for party and politician binds."""
    reports: dict[str, pd.DataFrame] = {}

    if "party_bind_status" in frame.columns:
        reports["party_rows"] = (
            frame["party_bind_status"].value_counts(dropna=False).rename_axis("status").reset_index(name="rows")
        )
        reports["party_unmatched_labels"] = (
            frame.loc[frame["party_bind_status"].eq("unmatched"), "party_source_label"]
            .value_counts(dropna=False)
            .rename_axis("party_source_label")
            .reset_index(name="rows")
        )

    if "politician_bind_status" in frame.columns:
        reports["politician_rows"] = (
            frame["politician_bind_status"].value_counts(dropna=False).rename_axis("status").reset_index(name="rows")
        )
        reports["politician_unmatched_speakers"] = (
            frame.loc[frame["politician_bind_status"].eq("unmatched"), "speaker"]
            .value_counts(dropna=False)
            .rename_axis("speaker")
            .reset_index(name="rows")
        )

    return reports
