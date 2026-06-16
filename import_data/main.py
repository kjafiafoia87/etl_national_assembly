from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SPEECH_DATA_DIR = PROJECT_DIR / "data" / "speech" / "2011_2026"
DEFAULT_RAW_DIR = SPEECH_DATA_DIR / "raw"
DEFAULT_CONVERTED_DIR = SPEECH_DATA_DIR / "converted"
DEFAULT_CSV_FILE = SPEECH_DATA_DIR / "centralized_speeches.csv"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from converter import download_dila_debats as dila  # noqa: E402


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_first_text(root: ET.Element, tag_name: str) -> str:
    for element in root.iter():
        if _tag_name(element.tag) == tag_name and element.text:
            return element.text.strip()
    return ""


def _raw_num_seances(raw_dir: Path) -> dict[str, str]:
    num_seances: dict[str, str] = {}
    for xml_file in sorted(raw_dir.rglob("CRI_*.xml")):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError as error:
            print(f"XML ignore, parsing impossible: {xml_file} ({error})")
            continue
        num_seance = _find_first_text(root, "numSeance")
        if num_seance:
            num_seances[xml_file.name] = num_seance
    return num_seances


def enrich_converted_with_num_seance(raw_dir: Path, converted_dir: Path) -> int:
    """Copy raw XML numSeance into converted JSON documents."""
    num_seances = _raw_num_seances(raw_dir)
    if not num_seances:
        return 0

    updated = 0
    for json_file in sorted(converted_dir.rglob("*.json")):
        with json_file.open(encoding="utf-8") as input_file:
            document = json.load(input_file)

        source_files = document.get("source_files") or []
        if isinstance(source_files, str):
            source_files = [source_files]

        num_seance = next(
            (
                num_seances[Path(source_file).name]
                for source_file in source_files
                if Path(source_file).name in num_seances
            ),
            "",
        )
        if not num_seance or document.get("numSeance") == num_seance:
            continue

        document["numSeance"] = num_seance
        with json_file.open("w", encoding="utf-8") as output_file:
            json.dump(document, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")
        updated += 1
    return updated


def add_common_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=dila.DEFAULT_BASE_URL, help="Index DILA source.")
    parser.add_argument("--years", help="Annees a telecharger, ex: 2011-2026 ou 2024,2025,2026.")
    parser.add_argument("--start-year", type=int, default=dila.DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--archive-dir", type=Path, help="Dossier de stockage temporaire ou permanent des .taz.")
    parser.add_argument("--keep-archives", action="store_true", help="Conserver les .taz dans --archive-dir.")
    parser.add_argument("--force-download", action="store_true", help="Retelecharger meme si des XML existent deja.")
    parser.add_argument("--dry-run", action="store_true", help="Lister sans telecharger.")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout reseau en secondes.")


def resolve_years(args: argparse.Namespace) -> list[int]:
    base_url = args.base_url.rstrip("/") + "/"
    if args.years:
        return dila.parse_years(args.years)

    years = [year for year in dila.available_years(base_url, args.timeout) if year >= args.start_year]
    if args.end_year is not None:
        years = [year for year in years if year <= args.end_year]
    return years


def run_download(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/") + "/"
    raw_dir = args.raw_dir.resolve()
    archive_dir = args.archive_dir.resolve() if args.archive_dir else None

    total_downloaded = 0
    total_skipped = 0
    for year in resolve_years(args):
        try:
            downloaded, skipped = dila.download_year(
                base_url=base_url,
                output_dir=raw_dir,
                archive_dir=archive_dir,
                year=year,
                timeout=args.timeout,
                force=args.force_download,
                keep_archives=args.keep_archives,
                dry_run=args.dry_run,
            )
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            tarfile.TarError,
            subprocess.CalledProcessError,
            ValueError,
        ) as error:
            print(f"erreur {year}: {error}")
            continue
        total_downloaded += downloaded
        total_skipped += skipped

    print(f"Archives telechargees/extraites: {total_downloaded}")
    print(f"Archives ignorees: {total_skipped}")


def run_convert(args: argparse.Namespace) -> None:
    from converter import convert as xml_to_json

    xml_to_json.run_internal_assertions()
    raw_dir = args.raw_dir.resolve()
    converted_dir = args.converted_dir.resolve()
    xml_to_json.convert(
        raw_dir,
        converted_dir,
        log_samples=args.log_context_samples,
    )
    updated = enrich_converted_with_num_seance(raw_dir, converted_dir)
    print(f"JSON enrichis avec numSeance: {updated}")


def run_csv(args: argparse.Namespace) -> None:
    from converter import json_to_csv

    if getattr(args, "raw_dir", None):
        updated = enrich_converted_with_num_seance(args.raw_dir.resolve(), args.converted_dir.resolve())
        print(f"JSON enrichis avec numSeance: {updated}")

    rows = json_to_csv.iter_rows(args.converted_dir.resolve())
    count = json_to_csv.write_csv(rows, args.csv_file.resolve())
    print(f"CSV cree: {args.csv_file.resolve()}")
    print(f"Lignes ecrites: {count}")


def run_all(args: argparse.Namespace) -> None:
    if not args.skip_download:
        run_download(args)
        if args.dry_run:
            return
    run_convert(args)
    run_csv(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pipeline DILA AN: download raw XML, convert JSON, build centralized CSV."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="DILA -> data/speech/2011_2026/raw")
    download_parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    add_common_download_args(download_parser)
    download_parser.set_defaults(func=run_download)

    convert_parser = subparsers.add_parser("convert", help="data/speech/2011_2026/raw -> data/speech/2011_2026/converted")
    convert_parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    convert_parser.add_argument("--converted-dir", type=Path, default=DEFAULT_CONVERTED_DIR)
    convert_parser.add_argument("--log-context-samples", action="store_true")
    convert_parser.set_defaults(func=run_convert)

    csv_parser = subparsers.add_parser("csv", help="data/speech/2011_2026/converted -> centralized_speeches.csv")
    csv_parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    csv_parser.add_argument("--converted-dir", type=Path, default=DEFAULT_CONVERTED_DIR)
    csv_parser.add_argument("--csv-file", type=Path, default=DEFAULT_CSV_FILE)
    csv_parser.set_defaults(func=run_csv)

    all_parser = subparsers.add_parser("all", help="Run download, convert, and csv steps")
    all_parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    all_parser.add_argument("--converted-dir", type=Path, default=DEFAULT_CONVERTED_DIR)
    all_parser.add_argument("--csv-file", type=Path, default=DEFAULT_CSV_FILE)
    all_parser.add_argument("--skip-download", action="store_true", help="Use existing raw XML.")
    all_parser.add_argument("--log-context-samples", action="store_true")
    add_common_download_args(all_parser)
    all_parser.set_defaults(func=run_all)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
