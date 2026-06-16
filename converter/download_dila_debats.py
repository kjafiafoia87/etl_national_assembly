from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


DEFAULT_BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA/Debats/AN/"
DEFAULT_START_YEAR = 2011


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value)


def parse_years(value: str) -> list[int]:
    years: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            if end < start:
                raise ValueError(f"Invalid year range: {part}")
            years.update(range(start, end + 1))
        else:
            years.add(int(part))
    return sorted(years)


def _read_index(base_url: str, timeout: int) -> list[str]:
    with urllib.request.urlopen(base_url, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    parser = _HrefParser()
    parser.feed(html)
    return parser.hrefs


def _archive_links(base_url: str, timeout: int) -> list[str]:
    links = []
    for href in _read_index(base_url, timeout):
        href_lower = href.lower()
        if href_lower.endswith((".taz", ".tar", ".tar.gz", ".tgz")):
            links.append(urllib.parse.urljoin(base_url, href))
    return sorted(set(links))


def _directory_years(base_url: str, timeout: int) -> list[int]:
    years = set()
    for href in _read_index(base_url, timeout):
        parsed_href = urllib.parse.urlparse(href).path.rstrip("/")
        name = Path(parsed_href).name
        if re.fullmatch(r"(?:19|20)\d{2}", name):
            years.add(int(name))
    return sorted(years)


def available_years(base_url: str = DEFAULT_BASE_URL, timeout: int = 60) -> list[int]:
    normalized_base_url = base_url.rstrip("/") + "/"
    years = set(_directory_years(normalized_base_url, timeout))
    for link in _archive_links(normalized_base_url, timeout):
        years.update(int(match) for match in re.findall(r"(?:19|20)\d{2}", Path(urllib.parse.urlparse(link).path).name))
    return sorted(years)


def _links_for_year(base_url: str, year: int, timeout: int) -> list[str]:
    year_text = str(year)
    normalized_base_url = base_url.rstrip("/") + "/"
    direct_links = [
        link
        for link in _archive_links(normalized_base_url, timeout)
        if year_text in Path(urllib.parse.urlparse(link).path).name
    ]
    year_url = urllib.parse.urljoin(normalized_base_url, f"{year}/")
    try:
        year_links = _archive_links(year_url, timeout)
    except urllib.error.URLError:
        year_links = []
    return sorted(set(direct_links + year_links))


def _year_has_xml(output_dir: Path, year: int) -> bool:
    year_dir = output_dir / str(year)
    return year_dir.exists() and any(year_dir.rglob("*.xml"))


def _download(url: str, destination: Path, timeout: int) -> None:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def _write_xml_member(archive: tarfile.TarFile, member: tarfile.TarInfo, year_dir: Path, year: int) -> bool:
    member_path = Path(member.name)
    parts = member_path.parts
    if parts and parts[0] == str(year):
        relative_path = Path(*parts[1:])
    else:
        relative_path = member_path
    target = (year_dir / relative_path).resolve()
    if year_dir.resolve() not in target.parents:
        raise tarfile.TarError(f"Unsafe archive path: {member.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    source = archive.extractfile(member)
    if source is None:
        return False
    with source, target.open("wb") as output:
        shutil.copyfileobj(source, output)
    return True


def _extract_xml_from_archive(archive: tarfile.TarFile, year_dir: Path, year: int) -> int:
    extracted = 0
    for member in archive.getmembers():
        if not member.isfile():
            continue
        member_name = member.name.lower()
        if member_name.endswith(".xml"):
            if _write_xml_member(archive, member, year_dir, year):
                extracted += 1
            continue
        if member_name.endswith((".tar", ".tar.gz", ".tgz", ".taz")):
            source = archive.extractfile(member)
            if source is None:
                continue
            with source, tarfile.open(fileobj=source) as nested_archive:
                extracted += _extract_xml_from_archive(nested_archive, year_dir, year)
    return extracted


def _safe_extract_xml(archive_path: Path, output_dir: Path, year: int) -> int:
    year_dir = output_dir / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path) as archive:
        return _extract_xml_from_archive(archive, year_dir, year)


def download_year(
    *,
    base_url: str = DEFAULT_BASE_URL,
    output_dir: Path,
    archive_dir: Path | None,
    year: int,
    timeout: int = 60,
    force: bool = False,
    keep_archives: bool = False,
    dry_run: bool = False,
) -> tuple[int, int]:
    if _year_has_xml(output_dir, year) and not force:
        print(f"{year}: XML deja presents, telechargement ignore")
        return 0, 1

    links = _links_for_year(base_url, year, timeout)
    if not links:
        print(f"{year}: aucune archive trouvee")
        return 0, 0

    if dry_run:
        for link in links:
            print(link)
        return 0, len(links)

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    archive_root = archive_dir if keep_archives else Path(tempfile.mkdtemp(prefix="dila_debats_"))
    archive_root.mkdir(parents=True, exist_ok=True)
    try:
        for link in links:
            archive_path = archive_root / Path(urllib.parse.urlparse(link).path).name
            print(f"{year}: telechargement {archive_path.name}")
            _download(link, archive_path, timeout)
            extracted = _safe_extract_xml(archive_path, output_dir, year)
            if extracted == 0:
                raise tarfile.TarError(f"Aucun XML extrait de {archive_path.name}")
            downloaded += 1
    except urllib.error.URLError:
        raise
    finally:
        if not keep_archives and archive_dir is None:
            shutil.rmtree(archive_root, ignore_errors=True)

    return downloaded, 0
