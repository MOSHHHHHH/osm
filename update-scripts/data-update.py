#!/usr/bin/env python3
"""
data-update.py
==============
Runs daily (00:00) or manually. Two independent jobs:

1. OsmAnd  - compares https://download.osmand.net/list.php against data/osmand-data.json.
             For every *.obf.zip that is new or was updated after our stored date:
             download the zip, extract the .obf file into files/, and update
             data/osmand-data.json. Non-.obf files inside the OsmAnd list are ignored
             entirely (never downloaded, never recorded).

2. Moovitdos - finds the current release zip URL and, if it changed, updates
               data/moovitdos-link.json. The actual zip is never copied into this repo;
               only the absolute URL is stored (the app downloads it directly from GitHub).

Both jobs always finish by writing data/update-status.json, which records whether each
job succeeded on this run and when the attempt was made. A failure in one job never stops
the other job from running.

Date format used everywhere in this project: ISO-8601 "YYYY-MM-DD" (date only, since none
of the upstream sources provide finer resolution than a day).
"""

import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
FILES_DIR = ROOT_DIR / "files"

OSMAND_DATA_JSON = DATA_DIR / "osmand-data.json"
MOOVITDOS_LINK_JSON = DATA_DIR / "moovitdos-link.json"
UPDATE_STATUS_JSON = DATA_DIR / "update-status.json"

OSMAND_LIST_URL = "https://download.osmand.net/list.php"
OSMAND_DOWNLOAD_BASE = "https://download.osmand.net/download"

# Moovitdos: the GitHub Pages site itself renders its download link with client-side
# JS, and the source repo appears to be private, so we can't rely on the public GitHub
# releases API. Instead we scrape the rendered page's HTML/inline data for a version
# string and build the well-known download URL pattern the app's developer confirmed:
#   https://github.com/moovitdos/moovidos/releases/download/v{VERSION}/moovidos_data_v{VERSION}.zip
MOOVITDOS_PAGE_URL = "https://moovitdos.github.io/moovidos/"
MOOVITDOS_URL_TEMPLATE = (
    "https://github.com/moovitdos/moovidos/releases/download/v{version}/moovidos_data_v{version}.zip"
)
# As a fallback path (in case the repo/releases are ever made public), also try the API.
MOOVITDOS_RELEASES_API = "https://api.github.com/repos/moovitdos/moovidos/releases/latest"

REQUEST_TIMEOUT = 60
USER_AGENT = "offline-maps-hub-bot/1.0 (+https://github.com/)"

HEADERS = {"User-Agent": USER_AGENT}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# OsmAnd
# ---------------------------------------------------------------------------

def parse_osmand_date(text: str):
    """OsmAnd list.php shows dates as dd.mm.yyyy. Returns ISO 'YYYY-MM-DD' or None."""
    text = text.strip()
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", text)
    if not m:
        return None
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def fetch_osmand_list():
    """Returns a list of dicts: {zip_name, zip_url, updatedDate} for every *.obf.zip row."""
    resp = requests.get(OSMAND_LIST_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    entries = []
    rows = soup.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue
        link = cells[0].find("a")
        if not link or not link.get("href"):
            continue
        zip_name = link.get_text(strip=True)
        if not zip_name.lower().endswith(".obf.zip"):
            continue  # Only OBF map files are ever downloaded or recorded.

        href = link["href"]
        if href.startswith("http"):
            zip_url = href
        else:
            zip_url = f"https://download.osmand.net/{href.lstrip('/')}"

        updated_date = None
        if len(cells) > 1:
            updated_date = parse_osmand_date(cells[1].get_text())

        entries.append({
            "zip_name": zip_name,
            "zip_url": zip_url,
            "updatedDate": updated_date or now_iso(),
        })

    return entries


def extract_obf_name_from_zip(zip_bytes: bytes):
    """Returns (obf_filename, obf_bytes) for the first .obf file found inside the zip."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".obf"):
                return Path(name).name, zf.read(name)
    return None, None


def update_osmand() -> bool:
    """Returns True on success (even if nothing changed), False on failure."""
    try:
        remote_entries = fetch_osmand_list()
    except Exception as exc:  # network / parsing failure
        print(f"[osmand] failed to fetch/parse list.php: {exc}", file=sys.stderr)
        return False

    stored = load_json(OSMAND_DATA_JSON, [])
    stored_by_name = {item["fileName"]: item for item in stored}

    had_error = False
    FILES_DIR.mkdir(parents=True, exist_ok=True)

    for entry in remote_entries:
        zip_name = entry["zip_name"]
        # The extracted .obf filename is the zip name without the trailing .zip
        # (this matches OsmAnd's own naming convention: X.obf.zip contains X.obf).
        expected_obf_name = zip_name[:-4] if zip_name.lower().endswith(".zip") else zip_name

        existing = stored_by_name.get(expected_obf_name)
        is_new = existing is None
        is_updated = (not is_new) and entry["updatedDate"] > existing.get("updatedDate", "")

        if not (is_new or is_updated):
            continue

        try:
            resp = requests.get(entry["zip_url"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            obf_name, obf_bytes = extract_obf_name_from_zip(resp.content)
            if obf_name is None:
                print(f"[osmand] no .obf file found inside {zip_name}, skipping", file=sys.stderr)
                continue

            (FILES_DIR / obf_name).write_bytes(obf_bytes)

            stored_by_name[obf_name] = {
                "fileName": obf_name,
                "updatedDate": entry["updatedDate"],
            }
            print(f"[osmand] updated {obf_name} ({entry['updatedDate']})")
        except Exception as exc:
            had_error = True
            print(f"[osmand] failed to process {zip_name}: {exc}", file=sys.stderr)
            continue

    save_json(OSMAND_DATA_JSON, list(stored_by_name.values()))
    return not had_error


# ---------------------------------------------------------------------------
# Moovitdos
# ---------------------------------------------------------------------------

VERSION_RE = re.compile(r"v?(\d+\.\d+\.\d+)")


def find_moovitdos_version_from_page() -> str:
    """Scrapes the Moovitdos GitHub Pages site for a version string like v1.0.168."""
    resp = requests.get(MOOVITDOS_PAGE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    matches = VERSION_RE.findall(resp.text)
    if not matches:
        raise ValueError("no version string found on Moovitdos page")
    # Pick the highest version present on the page (handles changelog history too).
    def version_key(v):
        return tuple(int(part) for part in v.split("."))
    matches.sort(key=version_key)
    return matches[-1]


def find_moovitdos_version_from_api() -> str:
    """Fallback: public GitHub releases API (works only if the repo/release is public)."""
    resp = requests.get(MOOVITDOS_RELEASES_API, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    tag = resp.json().get("tag_name", "")
    m = VERSION_RE.search(tag)
    if not m:
        raise ValueError(f"unexpected tag_name format: {tag!r}")
    return m.group(1)


def update_moovitdos() -> bool:
    try:
        try:
            version = find_moovitdos_version_from_page()
        except Exception as page_exc:
            print(f"[moovitdos] page scrape failed ({page_exc}), trying releases API", file=sys.stderr)
            version = find_moovitdos_version_from_api()

        new_url = MOOVITDOS_URL_TEMPLATE.format(version=version)
    except Exception as exc:
        print(f"[moovitdos] failed to determine current version: {exc}", file=sys.stderr)
        return False

    stored = load_json(MOOVITDOS_LINK_JSON, {"path": None, "updatedDate": None})

    if stored.get("path") != new_url:
        stored = {"path": new_url, "updatedDate": now_iso()}
        save_json(MOOVITDOS_LINK_JSON, stored)
        print(f"[moovitdos] updated link -> {new_url}")
    else:
        print("[moovitdos] link unchanged")

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    osmand_ok = update_osmand()
    moovitdos_ok = update_moovitdos()

    save_json(UPDATE_STATUS_JSON, {
        "osmand-status": osmand_ok,
        "moovitdos-status": moovitdos_ok,
        "update-date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    print(f"[done] osmand={'ok' if osmand_ok else 'FAILED'} "
          f"moovitdos={'ok' if moovitdos_ok else 'FAILED'}")


if __name__ == "__main__":
    main()
