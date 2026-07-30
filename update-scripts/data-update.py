#!/usr/bin/env python3
"""
data-update.py
==============
Runs every 20 minutes (or manually). Its only job is finding working download links for both
apps - not necessarily hosting every file ourselves:

1. OsmAnd  - compares https://download.osmand.net/list.php against data/osmand-data.json.
             For every *.obf.zip that is new, updated, or still only available via OsmAnd's own
             URL (see below), the script tries - within this run's time/size budget - to
             download the zip, extract the .obf, and upload it as an asset on this repo's own
             GitHub Release (so it can be served as a plain, ready-to-use .obf file). If that
             succeeds, data/osmand-data.json records our own Release URL and "zip-osm-file":
             false. If it doesn't succeed for any reason (ran out of time this run, the file is
             too large for a Release asset, a network error, anything) - that is NOT treated as
             an error - the script instead records OsmAnd's own original .zip URL directly and
             "zip-osm-file": true, so the file is always immediately downloadable either way,
             just sometimes as a .zip the user has to extract themselves. Every entry ALSO
             always stores "originalZipUrl" (OsmAnd's own link) regardless of hosting status,
             so the front-end can rely on it directly for the two flagship buttons (Israel/Yosh)
             without needing to search anything.

             If OsmAnd's list no longer contains a file we previously had, and this run's fetch
             of the list itself succeeded (see below), that file is removed from
             data/osmand-data.json and its Release asset (if we had uploaded one) is deleted.
             Its cached tag-rule-data.json/mapsTags.json entries are deliberately left alone,
             in case the file reappears later.

2. Moovitdos - queries the real GitHub Releases API for moovitdos/moovidos directly (no
               guessing) and finds the newest release with a .zip asset (ignoring .apk assets).
               If that zip's URL changed, updates data/moovitdos-link.json. The zip itself is
               never copied into this repo; only the absolute URL is stored.

--- Status ---
osmand-status is false ONLY if accessing/parsing OsmAnd's list.php itself failed this run.
Any number of individual files falling back to "zip-osm-file": true is normal, expected
behavior - not an error, and not a separate "in progress" status. There is no partial/pending
state anymore: a run either succeeded at reaching OsmAnd, or it didn't.

--- Priority order ---
Within a run's budget, Israel and Palestine (Yosh) are always processed first, then everything
else smallest-file-first, so the two flagship buttons and the largest number of total files
have the best chance of being fully hosted (not just linked) as quickly as possible.

Date format used everywhere in this project: ISO-8601 "YYYY-MM-DD" (date only, since none
of the upstream sources provide finer resolution than a day).
"""

import json
import os
import re
import sys
import tempfile
import time
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

MOOVITDOS_REPO = "moovitdos/moovidos"
MOOVITDOS_RELEASES_API = f"https://api.github.com/repos/{MOOVITDOS_REPO}/releases"
MOOVITDOS_PAGES_TO_CHECK = 5

REQUEST_TIMEOUT = 60
UPLOAD_TIMEOUT = 300
USER_AGENT = "offline-maps-hub-bot/1.0 (+https://github.com/)"
HEADERS = {"User-Agent": USER_AGENT}

RELEASE_TAG = "osmand-maps"
RELEASE_NAME = "OsmAnd map files (auto-managed - do not edit assets by hand)"
GITHUB_API = "https://api.github.com"

GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo", set automatically in Actions

# Files that must always resolve to a fixed, well-known name, regardless of upload status -
# the front-end's Israel/Yosh buttons look these two up directly by exact fileName.
PRIORITY_FILE_NAMES = ["israel_asia_2.obf", "palestine_asia_2.obf"]

MAX_OBF_FILE_SIZE_BYTES = 1900 * 1024 * 1024      # ~1.9GB, margin under GitHub's ~2GB per-asset cap
MAX_RUN_DOWNLOAD_BUDGET_BYTES = 2000 * 1024 * 1024  # bounds one run's network/runtime
MAX_ZIP_DOWNLOAD_BYTES = 1200 * 1024 * 1024       # sanity cap while streaming a zip to disk
MAX_RUN_SECONDS = 8 * 60  # internal deadline, safely under the job's timeout-minutes


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
# GitHub Release asset storage (our own repo)
# ---------------------------------------------------------------------------

def gh_headers(extra=None):
    h = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if extra:
        h.update(extra)
    return h


def public_read_headers():
    """For reading public data from a repo we don't own (Moovitdos). Attaching our own
    GITHUB_TOKEN still counts as an authenticated request (5,000/hour) instead of the
    unauthenticated limit (60/hour per IP), even though the token belongs to a different repo."""
    h = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if GH_TOKEN:
        h["Authorization"] = f"token {GH_TOKEN}"
    return h


def get_or_create_release():
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
            headers=gh_headers(), params={"per_page": 100, "page": page}, timeout=REQUEST_TIMEOUT,
        )
        assets_resp.raise_for_status()
        batch = assets_resp.json()
        if not batch:
            break
        for a in batch:
            assets[a["name"]] = a["id"]
        page += 1

    upload_url_base = release["upload_url"].split("{")[0]
    return release["id"], upload_url_base, assets


def delete_asset(asset_id: int):
    resp = requests.delete(
        f"{GITHUB_API}/repos/{GH_REPO}/releases/assets/{asset_id}", headers=gh_headers(), timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code not in (204, 404):
        resp.raise_for_status()


def upload_asset(upload_url_base: str, filename: str, file_path: Path) -> str:
    with file_path.open("rb") as f:
        resp = requests.post(
            upload_url_base, headers=gh_headers({"Content-Type": "application/octet-stream"}),
            params={"name": filename}, data=f, timeout=UPLOAD_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json()["browser_download_url"]


# ---------------------------------------------------------------------------
# OsmAnd list parsing
# ---------------------------------------------------------------------------

def parse_osmand_date(text: str):
    text = text.strip()
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", text)
    if not m:
        return None
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def parse_size_mb(text: str):
    text = text.strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def fetch_osmand_list():
    """Returns a list of dicts: {zip_name, zip_url, updatedDate, size_mb} for every *.obf.zip row."""
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
            continue

        href = link["href"]
        zip_url = href if href.startswith("http") else f"https://download.osmand.net/{href.lstrip('/')}"

        updated_date = None
        size_mb = None
        if len(cells) > 1:
            updated_date = parse_osmand_date(cells[1].get_text())
        if len(cells) > 2:
            size_mb = parse_size_mb(cells[2].get_text())

        entries.append({
            "zip_name": zip_name,
            "zip_url": zip_url,
            "updatedDate": updated_date or now_iso(),
            "size_mb": size_mb if size_mb is not None else 0.0,
        })

    return entries


def download_zip_to_temp(url: str) -> Path:
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
                    raise ValueError(f"zip exceeds sanity cap of {human(MAX_ZIP_DOWNLOAD_BYTES)}")
                tmp.write(chunk)
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    tmp.close()
    return Path(tmp.name)


def find_obf_entry(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".obf"):
                return Path(info.filename).name, info
    return None, None


def extract_obf_to_temp(zip_path: Path, zip_info) -> Path:
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


# ---------------------------------------------------------------------------
# OsmAnd update
# ---------------------------------------------------------------------------

def priority_sort_key(entry):
    expected_obf_name = entry["zip_name"][:-4] if entry["zip_name"].lower().endswith(".zip") else entry["zip_name"]
    is_priority = expected_obf_name.lower() in PRIORITY_FILE_NAMES
    return (0 if is_priority else 1, entry.get("size_mb", 0.0))


def update_osmand():
    """Returns dict with keys: ok (bool - only false on a genuine OsmAnd access/parse failure)."""
    try:
        remote_entries = fetch_osmand_list()
    except Exception as exc:
        print(f"[osmand] failed to fetch/parse list.php: {exc}", file=sys.stderr)
        return {"ok": False}

    stored = load_json(OSMAND_DATA_JSON, [])
    stored_by_name = {item["fileName"]: item for item in stored}

    remote_by_obf_name = {}
    for entry in remote_entries:
        obf_name = entry["zip_name"][:-4] if entry["zip_name"].lower().endswith(".zip") else entry["zip_name"]
        remote_by_obf_name[obf_name] = entry

    gh_release_ready = False
    upload_url_base = None
    existing_assets = {}
    try:
        release_id, upload_url_base, existing_assets = get_or_create_release()
        gh_release_ready = True
    except Exception as exc:
        print(f"[osmand] could not prepare GitHub Release for asset storage this run "
              f"(will still serve OsmAnd's own links): {exc}", file=sys.stderr)

    # --- Refresh every entry's baseline data from the fresh remote list (cheap, always done) ---
    for obf_name, remote in remote_by_obf_name.items():
        existing = stored_by_name.get(obf_name)
        is_new = existing is None
        is_updated = (not is_new) and remote["updatedDate"] > existing.get("updatedDate", "")

        if is_new or is_updated:
            # New or changed upstream: reset to the safe baseline (OsmAnd's own zip). This
            # may get upgraded to our own Release hosting below, budget permitting.
            stored_by_name[obf_name] = {
                "fileName": obf_name,
                "updatedDate": remote["updatedDate"],
                "url": remote["zip_url"],
                "zip-osm-file": True,
                "originalZipUrl": remote["zip_url"],
            }
        else:
            # Unchanged - just keep originalZipUrl/updatedDate fresh without touching hosting.
            existing["originalZipUrl"] = remote["zip_url"]
            existing["updatedDate"] = remote["updatedDate"]

    # --- Candidates to (re)upload this run: anything still on the OsmAnd fallback ---
    candidates = [
        {**remote_by_obf_name[name], "expected_obf_name": name}
        for name, item in stored_by_name.items()
        if item.get("zip-osm-file") and name in remote_by_obf_name
    ]
    candidates.sort(key=priority_sort_key)

    budget_used = 0
    start_time = time.monotonic()
    uploaded_this_run = 0

    if gh_release_ready:
        for entry in candidates:
            if time.monotonic() - start_time > MAX_RUN_SECONDS:
                break
            if budget_used >= MAX_RUN_DOWNLOAD_BUDGET_BYTES:
                break

            obf_name = entry["expected_obf_name"]
            zip_name = entry["zip_name"]
            tmp_zip = None
            tmp_obf = None
            try:
                tmp_zip = download_zip_to_temp(entry["zip_url"])
                found_name, zip_info = find_obf_entry(tmp_zip)
                if found_name is None:
                    print(f"[osmand] no .obf file found inside {zip_name}, leaving as OsmAnd link", file=sys.stderr)
                    continue

                obf_size = zip_info.file_size
                if obf_size > MAX_OBF_FILE_SIZE_BYTES:
                    print(f"[osmand] {obf_name} is {human(obf_size)}, over the safety margin - "
                          f"will keep serving OsmAnd's own link", file=sys.stderr)
                    continue
                if budget_used + obf_size > MAX_RUN_DOWNLOAD_BUDGET_BYTES:
                    continue  # doesn't fit this run's remaining budget - try again next run

                tmp_obf = extract_obf_to_temp(tmp_zip, zip_info)
                if found_name in existing_assets:
                    delete_asset(existing_assets[found_name])
                download_url = upload_asset(upload_url_base, found_name, tmp_obf)
                existing_assets[found_name] = None

                budget_used += obf_size
                uploaded_this_run += 1
                stored_by_name[obf_name]["url"] = download_url
                stored_by_name[obf_name]["zip-osm-file"] = False
                print(f"[osmand] uploaded {obf_name} ({human(obf_size)})")

            except Exception as exc:
                print(f"[osmand] could not upload {zip_name} this run, keeping OsmAnd's own "
                      f"link ({exc})", file=sys.stderr)
            finally:
                if tmp_zip is not None:
                    Path(tmp_zip).unlink(missing_ok=True)
                if tmp_obf is not None:
                    Path(tmp_obf).unlink(missing_ok=True)

    # --- Deletion: files OsmAnd no longer lists (only trustworthy because the fetch above
    #     succeeded - if it hadn't, we would have returned already with ok=False). ---
    removed = [name for name in stored_by_name if name not in remote_by_obf_name]
    for name in removed:
        item = stored_by_name.pop(name)
        if gh_release_ready and not item.get("zip-osm-file", True):
            asset_name = name  # the uploaded asset is named exactly like the obf file
            asset_id = existing_assets.get(asset_name)
            if asset_id:
                try:
                    delete_asset(asset_id)
                    print(f"[osmand] removed {name} (no longer listed by OsmAnd)")
                except Exception as exc:
                    print(f"[osmand] failed to delete stale asset {name}: {exc}", file=sys.stderr)
        else:
            print(f"[osmand] removed {name} (no longer listed by OsmAnd)")

    save_json(OSMAND_DATA_JSON, list(stored_by_name.values()))
    print(f"[osmand] this run uploaded {uploaded_this_run} file(s) ({human(budget_used)}), "
          f"{len(removed)} file(s) removed, "
          f"{sum(1 for v in stored_by_name.values() if v.get('zip-osm-file'))} still served "
          f"directly from OsmAnd")

    return {"ok": True}


# ---------------------------------------------------------------------------
# Moovitdos (unchanged logic from the previous version)
# ---------------------------------------------------------------------------

def find_latest_moovitdos_zip():
    for page in range(1, MOOVITDOS_PAGES_TO_CHECK + 1):
        resp = requests.get(
            MOOVITDOS_RELEASES_API, headers=public_read_headers(),
            params={"per_page": 30, "page": page}, timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        releases = resp.json()
        if not releases:
            break
        for release in releases:
            if release.get("draft") or release.get("prerelease"):
                continue
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                if name.lower().endswith(".zip"):
                    updated = (release.get("published_at") or release.get("created_at") or "")[:10]
                    return {"url": asset["browser_download_url"], "updatedDate": updated}
    raise ValueError(f"no release with a .zip asset found in the first "
                      f"{MOOVITDOS_PAGES_TO_CHECK} page(s) of {MOOVITDOS_REPO}/releases")


def update_moovitdos() -> bool:
    try:
        result = find_latest_moovitdos_zip()
    except Exception as exc:
        print(f"[moovitdos] failed to determine current release: {exc}", file=sys.stderr)
        return False

    stored = load_json(MOOVITDOS_LINK_JSON, {"path": None, "updatedDate": None})
    if stored.get("path") != result["url"]:
        save_json(MOOVITDOS_LINK_JSON, {"path": result["url"], "updatedDate": result["updatedDate"]})
        print(f"[moovitdos] updated link -> {result['url']}")
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
        "update-date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    print(f"[done] osmand={'ok' if osmand_result['ok'] else 'FAILED'} "
          f"moovitdos={'ok' if moovitdos_ok else 'FAILED'}")


if __name__ == "__main__":
    main()
