#!/usr/bin/env python3
"""Compatibility entry point and small CSV augmentation helper."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from convert_acteurs_to_csv import (
    MANDATE_COLUMNS,
    POLITICIAN_COLUMNS,
    clean,
    main as full_generation_main,
    write_csv,
)


def mp_id_from_deputy_url(url: str) -> str:
    """Extract the PA identifier used by local CSV tables from an AN URL."""
    dyn_match = re.search(r"/dyn/deputes/(PA\d+)\b", url)
    if dyn_match:
        return dyn_match.group(1)

    legacy_match = re.search(r"/fiches_id/(\d+)\.asp\b", url)
    if legacy_match:
        return f"PA{legacy_match.group(1)}"

    raise ValueError(f"URL député non reconnue: {url}")


def dataframe_rows(frame: pd.DataFrame) -> list[dict[str, str]]:
    return [
        {column: clean(row.get(column)) for column in frame.columns}
        for row in frame.to_dict(orient="records")
    ]


def merge_rows(
    existing: pd.DataFrame,
    additions: pd.DataFrame,
    key_columns: list[str],
) -> pd.DataFrame:
    if additions.empty:
        return existing

    existing_keys = {
        tuple(clean(row.get(column)) for column in key_columns)
        for row in existing.to_dict(orient="records")
    }
    new_rows = []
    for row in additions.to_dict(orient="records"):
        key = tuple(clean(row.get(column)) for column in key_columns)
        if key not in existing_keys:
            existing_keys.add(key)
            new_rows.append(row)

    if not new_rows:
        return existing
    return pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)


def augment_from_reference_csvs(args: argparse.Namespace) -> None:
    mp_ids = []
    for url in args.deputy_url:
        mp_id = mp_id_from_deputy_url(url)
        if mp_id not in mp_ids:
            mp_ids.append(mp_id)

    reference_politicians = pd.read_csv(args.reference_politician_csv, dtype=str).fillna("")
    reference_mandates = pd.read_csv(args.reference_mandate_csv, dtype=str).fillna("")

    politician_additions = reference_politicians[
        reference_politicians["mp_id"].isin(mp_ids)
    ].copy()
    mandate_additions = reference_mandates[reference_mandates["mp_id"].isin(mp_ids)].copy()

    missing = sorted(set(mp_ids) - set(politician_additions["mp_id"]))
    if missing:
        raise RuntimeError(
            "Aucune ligne politician.csv de référence pour: " + ", ".join(missing)
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    politician_out = args.out_dir / "politician.csv"
    mandate_out = args.out_dir / "mandate.csv"

    existing_politicians = (
        pd.read_csv(politician_out, dtype=str).fillna("")
        if politician_out.exists()
        else pd.DataFrame(columns=POLITICIAN_COLUMNS)
    )
    existing_mandates = (
        pd.read_csv(mandate_out, dtype=str).fillna("")
        if mandate_out.exists()
        else pd.DataFrame(columns=MANDATE_COLUMNS)
    )

    merged_politicians = merge_rows(
        existing_politicians, politician_additions, ["mp_id"]
    )
    merged_mandates = merge_rows(
        existing_mandates, mandate_additions, ["mp_id", "term"]
    )

    if args.dry_run:
        print("Dry run: CSV files were not modified")
    else:
        write_csv(
            politician_out,
            POLITICIAN_COLUMNS,
            dataframe_rows(merged_politicians[POLITICIAN_COLUMNS]),
        )
        write_csv(
            mandate_out,
            MANDATE_COLUMNS,
            dataframe_rows(merged_mandates[MANDATE_COLUMNS]),
        )

    print("Requested URLs:")
    for url, mp_id in zip(args.deputy_url, [mp_id_from_deputy_url(url) for url in args.deputy_url]):
        print(f"- {url} -> {mp_id}")
    print(f"Reference politicians found: {len(politician_additions)}")
    print(f"Reference mandates found: {len(mandate_additions)}")
    print(f"Output politicians: {len(merged_politicians)}")
    print(f"Output mandates: {len(merged_mandates)}")
    print(f"Politician CSV: {politician_out}")
    print(f"Mandate CSV: {mandate_out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--deputy-url",
        action="append",
        default=[],
        help="Assemblée nationale deputy URL to add from reference CSVs. Repeatable.",
    )
    parser.add_argument(
        "--reference-politician-csv",
        default=Path("data/final/politician.csv"),
        type=Path,
    )
    parser.add_argument(
        "--reference-mandate-csv",
        default=Path("data/final/mandate.csv"),
        type=Path,
    )
    parser.add_argument("--out-dir", default=Path("data/output"), type=Path)
    parser.add_argument("--dry-run", action="store_true")

    args, remaining = parser.parse_known_args()
    if args.deputy_url:
        if remaining:
            parser.error("--deputy-url mode does not accept full-generation options")
        augment_from_reference_csvs(args)
        return

    full_generation_main()


if __name__ == "__main__":
    main()
