#!/usr/bin/env python3
"""
data-update.py
==============
Runs every 3 minutes (or manually). Two independent jobs:

1. OsmAnd  - compares https://download.osmand.net/list.php against data/osmand-data.json.
             For every *.obf.zip that is new or was updated after our stored date:
             download the zip, extract the .obf file, and upload it as an asset on a
             dedicated GitHub Release (tag RELEASE_TAG) in this same repo - never as a
             git-tracked file. data/osmand-data.json is then updated with the file's
             permanent download URL. Non-.obf files inside the OsmAnd list are ignored
             entirely (never downloaded, never recorded).

2. Moovitdos - finds the current release zip URL and, if it changed, updates
               data/moovitdos-link.json. The actual zip is never copied into this repo;
               only the absolute URL is stored (the app downloads it directly from GitHub).

--- Why release assets instead of committing files to git -----------------------
Git (and GitHub's push receiver) hard-blocks any single file over 100MB. Many real
OsmAnd country files are 100-350MB+, so committing them as normal git blobs is a dead
end no matter how small a safety margin is used - most files would simply never fit.

GitHub Release assets are a separate mechanism (the same one Moovitdos itself uses for
its own zip): each asset can be up to ~2GB, and uploading one does not touch git history
or push size at all - only the tiny JSON files in data/ are ever committed. This is what
lets "almost every" map import automatically, not just the small ones.

  MAX_OBF_FILE_SIZE_BYTES     - a single extracted .obf file must be under this to ever
                                 be uploaded. Comfortably under GitHub's ~2GB per-asset
                                 limit; in practice no real OsmAnd file should hit this.
  MAX_RUN_DOWNLOAD_BUDGET_BYTES - total bytes downloaded+uploaded in a single run. This
                                 no longer exists to dodge a git limit - it just keeps
                                 each 3-minute run's network/runtime bounded. Anything
                                 that doesn't fit is retried automatically next run.
  MAX_ZIP_DOWNLOAD_BYTES      - sanity cap while streaming a zip download, so we never
                                 hold an unbounded amount of data on disk while probing it.
-----------------------------------------------------------------------------------

Both jobs always finish by writing data/update-status.json, which records whether each
job succeeded on this run, whether OsmAnd import is still catching up on a backlog, and
when the attempt was made. A failure in one job never stops the other job from running.

Date format used everywhere in this project: ISO-8601 "YYYY-MM-DD" (date only, since none
of the upstream sources provide finer resolution than a day).
"""

import json
import os
import re
import sys
import tempfile
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

OSMAND_DATA_JSON = DATA_DIR / "osmand-data.json"
MOOVITDOS_LINK_JSON = DATA_DIR / "moovitdos-link.json"
UPDATE_STATUS_JSON = DATA_DIR / "update-status.json"

OSMAND_LIST_URL = "https://download.osmand.net/list.php"

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
UPLOAD_TIMEOUT = 300
USER_AGENT = "offline-maps-hub-bot/1.0 (+https://github.com/)"
HEADERS = {"User-Agent": USER_AGENT}

# --- This repo's own GitHub Release used as OBF file storage ---
RELEASE_TAG = "osmand-maps"
RELEASE_NAME = "OsmAnd map files (auto-managed - do not edit assets by hand)"
GITHUB_API = "https://api.github.com"

GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo", set automatically in Actions

# --- Size safety margins (see module docstring) ---
MAX_OBF_FILE_SIZE_BYTES = 1900 * 1024 * 1024      # ~1.9GB, margin under GitHub's ~2GB per-asset cap
MAX_RUN_DOWNLOAD_BUDGET_BYTES = 2000 * 1024 * 1024  # bounds one run's network/runtime, not a git limit
MAX_ZIP_DOWNLOAD_BYTES = 1200 * 1024 * 1024       # sanity cap while streaming a zip to disk


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


def human(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f}MB"


# ---------------------------------------------------------------------------
# GitHub Release asset storage
# ---------------------------------------------------------------------------

def gh_headers(extra=None):
    h = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if extra:
        h.update(extra)
    return h


def get_or_create_release():
    """Returns (release_id, upload_url_base, {asset_name: asset_id})."""
    url = f"{GITHUB_API}/repos/{GH_REPO}/releases/tags/{RELEASE_TAG}"
    resp = requests.get(url, headers=gh_headers(), timeout=REQUEST_TIMEOUT)

    if resp.status_code == 404:
        create_resp = requests.post(
            f"{GITHUB_API}/repos/{GH_REPO}/releases",
            headers=gh_headers(),
            json={
                "tag_name": RELEASE_TAG,
                "name": RELEASE_NAME,
                "body": "Auto-managed storage for OsmAnd .obf map files. Do not edit assets by hand.",
                "draft": False,
                "prerelease": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        create_resp.raise_for_status()
        release = create_resp.json()
    else:
        resp.raise_for_status()
        release = resp.json()

    assets = {}
    page = 1
    while True:
        assets_resp = requests.get(
            f"{GITHUB_API}/repos/{GH_REPO}/releases/{release['id']}/assets",
            headers=gh_headers(),
            params={"per_page": 100, "page": page},
            timeout=REQUEST_TIMEOUT,
        )
        assets_resp.raise_for_status()
        batch = assets_resp.json()
        if not batch:
            break
        for a in batch:
            assets[a["name"]] = a["id"]
        page += 1

    upload_url_base = release["upload_url"].split("{")[0]  # strip the {?name,label} template
    return release["id"], upload_url_base, assets


def delete_asset(asset_id: int):
    resp = requests.delete(
        f"{GITHUB_API}/repos/{GH_REPO}/releases/assets/{asset_id}",
        headers=gh_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code not in (204, 404):
        resp.raise_for_status()


def upload_asset(upload_url_base: str, filename: str, file_path: Path) -> str:
    """Uploads file_path as a release asset named filename. Returns the permanent
    download URL. Streams from disk rather than loading the whole file into memory."""
    with file_path.open("rb") as f:
        resp = requests.post(
            upload_url_base,
            headers=gh_headers({"Content-Type": "application/octet-stream"}),
            params={"name": filename},
            data=f,
            timeout=UPLOAD_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json()["browser_download_url"]


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
    for row in soup.find_all("tr"):
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
        zip_url = href if href.startswith("http") else f"https://download.osmand.net/{href.lstrip('/')}"

        updated_date = None
        if len(cells) > 1:
            updated_date = parse_osmand_date(cells[1].get_text())

        entries.append({
            "zip_name": zip_name,
            "zip_url": zip_url,
            "updatedDate": updated_date or now_iso(),
        })

    return entries


def download_zip_to_temp(url: str) -> Path:
    """Streams the zip to a temp file on disk, aborting if it exceeds the sanity cap.
    Never buffers the whole file in memory."""
    tmp = tempfile.NamedTemporaryFile(prefix="osmand_", suffix=".zip", delete=False)
    downloaded = 0
    try:
        with requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_ZIP_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"zip exceeds sanity cap of {human(MAX_ZIP_DOWNLOAD_BYTES)} while downloading"
                    )
                tmp.write(chunk)
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    tmp.close()
    return Path(tmp.name)


def find_obf_entry(zip_path: Path):
    """Returns (obf_name, ZipInfo) for the first .obf entry in the zip, or (None, None)."""
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".obf"):
                return Path(info.filename).name, info
    return None, None


def extract_obf_to_temp(zip_path: Path, zip_info) -> Path:
    """Extracts the given entry to its own temp file on disk (not held in memory)."""
    fd, tmp_name = tempfile.mkstemp(prefix="obf_", suffix=".obf")
    os.close(fd)
    dest = Path(tmp_name)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(zip_info) as src, dest.open("wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    return dest


def update_osmand():
    """Returns dict with keys: ok, in_progress, pending_files, oversized_files."""
    if not GH_TOKEN or not GH_REPO:
        print("[osmand] GITHUB_TOKEN / GITHUB_REPOSITORY not set - can only run inside "
              "a GitHub Actions workflow with a token available", file=sys.stderr)
        return {"ok": False, "in_progress": False, "pending_files": [], "oversized_files": []}

    try:
        remote_entries = fetch_osmand_list()
    except Exception as exc:  # network / parsing failure
        print(f"[osmand] failed to fetch/parse list.php: {exc}", file=sys.stderr)
        return {"ok": False, "in_progress": False, "pending_files": [], "oversized_files": []}

    try:
        release_id, upload_url_base, existing_assets = get_or_create_release()
    except Exception as exc:
        print(f"[osmand] failed to prepare GitHub Release for asset storage: {exc}", file=sys.stderr)
        return {"ok": False, "in_progress": False, "pending_files": [], "oversized_files": []}

    stored = load_json(OSMAND_DATA_JSON, [])
    stored_by_name = {item["fileName"]: item for item in stored}

    # Preserve previously known oversized files (they never get retried automatically;
    # they only leave this list if list.php stops offering them, or the size cap is raised
    # and a future manual run succeeds).
    previous_status = load_json(UPDATE_STATUS_JSON, {})
    oversized_files = set(previous_status.get("osmand-oversized-files", []))

    # Build the list of candidates that need importing (new, or updated since we last saw them).
    candidates = []
    for entry in remote_entries:
        zip_name = entry["zip_name"]
        expected_obf_name = zip_name[:-4] if zip_name.lower().endswith(".zip") else zip_name

        if expected_obf_name in oversized_files:
            continue  # known to be too large; don't keep re-downloading it every 3 minutes

        existing = stored_by_name.get(expected_obf_name)
        is_new = existing is None
        is_updated = (not is_new) and entry["updatedDate"] > existing.get("updatedDate", "")
        if is_new or is_updated:
            candidates.append({**entry, "expected_obf_name": expected_obf_name})

    had_error = False
    pending_files = []
    budget_used = 0

    for entry in candidates:
        zip_name = entry["zip_name"]
        tmp_zip = None
        tmp_obf = None

        try:
            tmp_zip = download_zip_to_temp(entry["zip_url"])
            obf_name, zip_info = find_obf_entry(tmp_zip)

            if obf_name is None:
                print(f"[osmand] no .obf file found inside {zip_name}, skipping", file=sys.stderr)
                continue

            obf_size = zip_info.file_size  # uncompressed size = actual asset size once uploaded

            if obf_size > MAX_OBF_FILE_SIZE_BYTES:
                oversized_files.add(obf_name)
                print(f"[osmand] {obf_name} is {human(obf_size)}, over the "
                      f"{human(MAX_OBF_FILE_SIZE_BYTES)} safety margin - will not be "
                      f"imported automatically", file=sys.stderr)
                continue

            if budget_used + obf_size > MAX_RUN_DOWNLOAD_BUDGET_BYTES:
                # Doesn't fit in what's left of this run's network/runtime budget - leave
                # it for the next run (in 3 minutes) rather than making this run too long.
                pending_files.append(obf_name)
                continue

            tmp_obf = extract_obf_to_temp(tmp_zip, zip_info)

            # Assets are immutable once uploaded - if we're updating a file, delete the
            # old asset first so the name can be reused.
            if obf_name in existing_assets:
                delete_asset(existing_assets[obf_name])

            download_url = upload_asset(upload_url_base, obf_name, tmp_obf)
            existing_assets[obf_name] = None  # name is now taken again this run

            budget_used += obf_size
            stored_by_name[obf_name] = {
                "fileName": obf_name,
                "updatedDate": entry["updatedDate"],
                "url": download_url,
            }
            print(f"[osmand] uploaded {obf_name} ({human(obf_size)}, {entry['updatedDate']})")

        except Exception as exc:
            had_error = True
            print(f"[osmand] failed to process {zip_name}: {exc}", file=sys.stderr)
        finally:
            if tmp_zip is not None:
                Path(tmp_zip).unlink(missing_ok=True)
            if tmp_obf is not None:
                Path(tmp_obf).unlink(missing_ok=True)

    save_json(OSMAND_DATA_JSON, list(stored_by_name.values()))

    print(f"[osmand] this run uploaded {human(budget_used)} "
          f"({len(pending_files)} file(s) deferred to next run, "
          f"{len(oversized_files)} file(s) permanently oversized)")

    return {
        "ok": not had_error,
        "in_progress": len(pending_files) > 0,
        "pending_files": pending_files,
        "oversized_files": sorted(oversized_files),
    }


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
        save_json(MOOVITDOS_LINK_JSON, {"path": new_url, "updatedDate": now_iso()})
        print(f"[moovitdos] updated link -> {new_url}")
    else:
        print("[moovitdos] link unchanged")

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    osmand_result = update_osmand()
    moovitdos_ok = update_moovitdos()

    save_json(UPDATE_STATUS_JSON, {
        "osmand-status": osmand_result["ok"],
        "moovitdos-status": moovitdos_ok,
        "osmand-in-progress": osmand_result["in_progress"],
        "osmand-pending-files": osmand_result["pending_files"],
        "osmand-oversized-files": osmand_result["oversized_files"],
        "update-date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    print(f"[done] osmand={'ok' if osmand_result['ok'] else 'FAILED'} "
          f"(in_progress={osmand_result['in_progress']}) "
          f"moovitdos={'ok' if moovitdos_ok else 'FAILED'}")


if __name__ == "__main__":
    main()
