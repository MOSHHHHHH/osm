#!/usr/bin/env python3
"""
tag-generator.py
================
Runs daily (06:00) or manually. For every file listed in data/osmand-data.json that
does not yet have an entry in data/mapsTags.json, asks the Gemini API for a small
tag object (continent/country/city in Hebrew and English, plus one emoji) and appends
it to data/mapsTags.json.

Requests are sent back-to-back with no delay between them (per spec). If a response is
missing, malformed, or not valid JSON, the same file is retried after a 60 second pause,
up to 10 attempts, with the attempt counter reset to zero as soon as any request succeeds.
If 10 consecutive failures happen, the script simply saves what it has and exits - this
is a normal, expected stopping condition, not an error (exit code 0).
"""

import json
import re
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

OSMAND_DATA_JSON = DATA_DIR / "osmand-data.json"
MAPS_TAGS_JSON = DATA_DIR / "mapsTags.json"
UPDATE_STATUS_JSON = DATA_DIR / "update-status.json"

import os
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)

MAX_ATTEMPTS_PER_FILE = 10
RETRY_DELAY_SECONDS = 60
REQUEST_TIMEOUT = 60

TAG_SCHEMA = {
    "continent": "string or null",
    "country": "string or null",
    "city": "string or null",
}

PROMPT_TEMPLATE = """For the map file
{filename}

Create tags, in Hebrew and English, in JSON format, according to the following schema exactly. Do not make up details and do not respond to anything else in reply except the JSON object.

The tags include continent, country, city, and emoji.

Respond with ONLY a single JSON object shaped exactly like this (no markdown fences, no commentary):
{{
  "hebrewTags": {{"continent": "...", "country": "...", "city": "..."}},
  "englishTags": {{"continent": "...", "country": "...", "city": "..."}},
  "emoji": "..."
}}

Any field that does not apply must be JSON null, never an empty string or a guess.
If the map includes multiple cities or countries, leave the relevant tag (city and/or
country) empty - null - rather than guessing one. However, if the map covers the entire
world, set the "continent" tag to "world" ("עולם" in hebrewTags) instead of null.

CONTINENT: choose the englishTags.continent value from EXACTLY this fixed list (and use the
matching hebrewTags.continent value shown beside it) - never invent or paraphrase a different
wording, even if it seems more natural:
  Africa / אפריקה
  Asia / אסיה
  Europe / אירופה
  North America / צפון אמריקה
  South America / דרום אמריקה
  Australia and Oceania / אוסטרליה ואוקיאניה
  Antarctica / אנטארקטיקה
  World / עולם (only for a file covering the entire world - see above)

TERRITORIES AND DEPENDENCIES: if the file covers an external territory, dependency, or
uninhabited island group that belongs to a sovereign country (for example Ashmore and Cartier
Islands, or the Coral Sea Islands, which both belong to Australia), set "country" to that
sovereign country's own name (e.g. "Australia" / "אוסטרליה"), not the territory's own name.
Only set "city" if the file is scoped to one specific city/locality within that country.

EMOJI: the emoji must always be the real, standard flag emoji of the ISO 3166-1 country in
the "country" field (matching its two-letter country code) - never a generic, decorative, or
thematic emoji (no palm trees, animals, landmarks, or generic map/island icons), even for
small territories or islands. If "country" is null and the file is a whole continent (e.g.
Antarctica) or the whole world, use that region's own standard flag/globe emoji instead
(Antarctica -> the Antarctica flag emoji; World -> 🌐). Examples of correct emoji: Argentina
-> 🇦🇷, Brazil -> 🇧🇷, an Australian external territory -> 🇦🇺 (never a palm tree or other icon).
"""


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
# JSON extraction / repair helpers
# ---------------------------------------------------------------------------

def try_parse_json(text: str):
    """Attempts several increasingly aggressive strategies to pull a JSON object
    out of a model response. Returns the parsed dict, or None if all strategies fail."""

    candidates = [text.strip()]

    # Strip markdown code fences (```json ... ``` or ``` ... ```).
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    # Grab the first {...} block (greedy, balanced-ish) in case of leading/trailing prose.
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(0).strip())

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Last resort: common formatting mistakes (trailing commas, single quotes).
    for candidate in candidates:
        repaired = candidate
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)  # trailing commas
        repaired = re.sub(r"'", '"', repaired)  # single -> double quotes
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            continue

    return None


def normalize_tag_object(raw: dict, filename: str):
    """Validates shape and fills in the expected keys, defaulting missing values to None."""

    def sub(d):
        d = d or {}
        return {
            "continent": d.get("continent") or None,
            "country": d.get("country") or None,
            "city": d.get("city") or None,
        }

    return {
        "fileName": filename,
        "hebrewTags": sub(raw.get("hebrewTags")),
        "englishTags": sub(raw.get("englishTags")),
        "emoji": raw.get("emoji") or None,
    }


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

def call_gemini(filename: str):
    """Returns the raw text response from Gemini, or raises on transport failure."""
    prompt = PROMPT_TEMPLATE.format(filename=filename)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
    }
    resp = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["candidates"][0]["content"]["parts"][0]["text"]


def generate_tags_for_file(filename: str):
    """Returns a normalized tag dict, or None if MAX_ATTEMPTS_PER_FILE was exhausted."""
    attempts = 0
    while attempts < MAX_ATTEMPTS_PER_FILE:
        try:
            raw_text = call_gemini(filename)
            parsed = try_parse_json(raw_text)
            if parsed is not None:
                return normalize_tag_object(parsed, filename)
            print(f"[tags] invalid JSON for {filename}, attempt {attempts + 1}/{MAX_ATTEMPTS_PER_FILE}",
                  file=sys.stderr)
        except Exception as exc:
            print(f"[tags] request failed for {filename}: {exc} "
                  f"(attempt {attempts + 1}/{MAX_ATTEMPTS_PER_FILE})", file=sys.stderr)

        attempts += 1
        if attempts < MAX_ATTEMPTS_PER_FILE:
            time.sleep(RETRY_DELAY_SECONDS)

    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not GEMINI_API_KEY:
        print("[tags] GEMINI_API_KEY is not set, aborting", file=sys.stderr)
        sys.exit(1)

    status = load_json(UPDATE_STATUS_JSON, {})
    if status.get("osmand-in-progress"):
        print("[tags] OsmAnd import is still catching up on a backlog "
              "(osmand-in-progress=true) - doing nothing this run.")
        sys.exit(0)

    osmand_files = load_json(OSMAND_DATA_JSON, [])
    existing_tags = load_json(MAPS_TAGS_JSON, [])
    tagged_names = {t["fileName"] for t in existing_tags}

    pending = [f["fileName"] for f in osmand_files if f["fileName"] not in tagged_names]
    print(f"[tags] {len(pending)} file(s) need tags")

    consecutive_failures = 0

    for filename in pending:
        result = generate_tags_for_file(filename)

        if result is None:
            consecutive_failures += 1
            print(f"[tags] giving up on {filename} after {MAX_ATTEMPTS_PER_FILE} attempts")
            if consecutive_failures >= 10:
                print("[tags] 10 consecutive failures reached - saving progress and stopping "
                      "(this is a normal stopping condition, not an error)")
                break
            continue

        consecutive_failures = 0
        existing_tags.append(result)
        # Save after every success so progress is never lost mid-run.
        save_json(MAPS_TAGS_JSON, existing_tags)
        print(f"[tags] tagged {filename} -> {result['emoji']} "
              f"{result['hebrewTags']['country']}")

    save_json(MAPS_TAGS_JSON, existing_tags)
    print("[tags] done")


if __name__ == "__main__":
    main()
