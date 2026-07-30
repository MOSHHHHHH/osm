#!/usr/bin/env python3
"""
tag-rule-generator.py  (file 1 of 2 - the only script that calls the Gemini API)
==================================================================================
Scans every file in data/osmand-data.json, and for any country or region slug NOT yet
present in data/tag-rule-data.json, asks Gemini for the missing piece and writes it back into
tag-rule-data.json. It never touches data/mapsTags.json directly - that is entirely the job of
tag-generator.py (file 2), which is pure logic and re-derives everything from whatever is
currently in tag-rule-data.json.

Once a country or region is resolved here, it is resolved forever (until manually edited) - no
repeat AI calls, no repeat cost, and no repeat risk of the model giving a different answer on a
later run.

Retry strategy (unchanged from the original single-script design): requests are sent back to
back with no delay. If a request or its JSON is invalid, the same item is retried after a 60
second pause, up to 10 attempts, with the counter reset to zero as soon as any request
succeeds. If 10 consecutive failures happen (across items, not just one), the script simply
saves what it has and exits - a normal, expected stopping condition (exit code 0), not an error.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

from osmand_filename import parse_filename, region_prefix_keys, resolve_country

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

OSMAND_DATA_JSON = DATA_DIR / "osmand-data.json"
TAG_RULE_DATA_JSON = DATA_DIR / "tag-rule-data.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

MAX_ATTEMPTS_PER_ITEM = 10
RETRY_DELAY_SECONDS = 60
REQUEST_TIMEOUT = 60
MAX_CONSECUTIVE_FAILURES = 10

CONTINENT_LIST_TEXT = """  Africa / אפריקה
  Asia / אסיה
  Europe / אירופה
  North America / צפון אמריקה
  South America / דרום אמריקה
  Australia and Oceania / אוסטרליה ואוקיאניה
  Antarctica / אנטארקטיקה
  World / עולם (only if this literally covers the entire world)"""

COUNTRY_PROMPT_TEMPLATE = """A country/place slug taken from a map file name is: "{slug}"
(the slug uses hyphens instead of spaces, and may be an abbreviation).

Respond with ONLY a single JSON object, no markdown fences, no commentary, shaped exactly like:
{{
  "en": "...",
  "he": "...",
  "continentEn": "...",
  "continentHe": "...",
  "iso2": "XX" or null,
  "isRegionNotCountry": true or false,
  "thematicEmoji": "emoji" or null
}}

Rules:
- "en"/"he": the real, current, official common name of this place in English and Hebrew.
  Resolve abbreviations to their real name (e.g. "gb" -> "United Kingdom", "us" -> "United
  States"). Use each country's CURRENT official name even if the slug reflects an older name
  (e.g. a slug like "macedonia" refers to the country now officially called North Macedonia;
  "swaziland" refers to the country now officially called Eswatini).
- "continentEn"/"continentHe": choose EXACTLY one pair from this fixed list, never invent or
  paraphrase a different wording:
{continent_list}
  Base this on the country's real, commonly-known geographic classification - do not assume it
  matches whatever continent word might appear elsewhere in the source file name, since a map
  provider's own internal folder naming does not always match standard geography (for example,
  Turkey is normally classified as Asia and most of Russia's territory as Asia, regardless of
  what any internal folder name might suggest).
- "iso2": the real ISO 3166-1 alpha-2 two-letter code for this place if one exists, else null.
- "isRegionNotCountry": true only if this slug represents a broad multi-country
  region/grouping (like "Oceania" or "the Caribbean" as a whole) rather than one specific
  country or recognized territory - in that case "en"/"he" should describe the region/grouping
  itself, not name a specific country.
- "thematicEmoji": only used when "iso2" is null. Pick a real, standard flag emoji whenever a
  specific real country legitimately applies, even for small territories or dependencies -
  never a generic/decorative emoji (no palm trees, animals, landmarks) as a substitute for a
  real flag. Only when there truly is no single country (isRegionNotCountry=true, or a
  worldwide/non-national dataset) is a fitting generic or thematic emoji appropriate instead.
"""

REGION_PROMPT_TEMPLATE = """A file about {country_en} ({country_he} in Hebrew) has an internal
region/subregion path (from a map file name, using hyphens instead of spaces). The full path
so far, from broadest to most specific, is: {full_path}
The level you need to name is just the LAST part of that path: "{leaf_slug}"
{parent_context}

Respond with ONLY a single JSON object, no markdown fences, no commentary, shaped exactly like:
{{
  "en": "...",
  "he": "..."
}}

Give the real, properly capitalized/spaced display name of this specific region, state,
province, or city in English and Hebrew - not a guess or invention if you are not sure what it
refers to, but your best real identification of this specific place given the country and
parent context above.
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
# JSON extraction / repair helpers (same cascade as the original design)
# ---------------------------------------------------------------------------

def try_parse_json(text: str):
    candidates = [text.strip()]

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(0).strip())

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    for candidate in candidates:
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        repaired = re.sub(r"'", '"', repaired)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            continue

    return None


def call_gemini(prompt: str) -> str:
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()
    return body["candidates"][0]["content"]["parts"][0]["text"]


class ConsecutiveFailureBudgetExhausted(Exception):
    pass


def resolve_item(prompt: str, item_label: str, consecutive_failures: list):
    """Returns the parsed JSON dict, or raises ConsecutiveFailureBudgetExhausted if the
    global consecutive-failure budget runs out. consecutive_failures is a 1-item list used
    as a mutable int cell shared across calls."""
    attempts = 0
    while attempts < MAX_ATTEMPTS_PER_ITEM:
        try:
            raw_text = call_gemini(prompt)
            parsed = try_parse_json(raw_text)
            if parsed is not None:
                consecutive_failures[0] = 0
                return parsed
            print(f"[rules] invalid JSON for {item_label}, attempt {attempts + 1}/{MAX_ATTEMPTS_PER_ITEM}",
                  file=sys.stderr)
        except Exception as exc:
            print(f"[rules] request failed for {item_label}: {exc} "
                  f"(attempt {attempts + 1}/{MAX_ATTEMPTS_PER_ITEM})", file=sys.stderr)

        attempts += 1
        if attempts < MAX_ATTEMPTS_PER_ITEM:
            time.sleep(RETRY_DELAY_SECONDS)

    consecutive_failures[0] += 1
    print(f"[rules] giving up on {item_label} after {MAX_ATTEMPTS_PER_ITEM} attempts "
          f"({consecutive_failures[0]} consecutive failures)")
    if consecutive_failures[0] >= MAX_CONSECUTIVE_FAILURES:
        raise ConsecutiveFailureBudgetExhausted()
    return None


# ---------------------------------------------------------------------------
# Scanning for missing items
# ---------------------------------------------------------------------------

def find_missing_items(osmand_files, rule_data):
    continent_suffix_map = rule_data.get("continentSuffixMap", {})
    countries = rule_data.get("countries", {})
    regions = rule_data.get("regions", {})
    special_files = rule_data.get("specialFiles", {})

    missing_country_slugs = []
    seen_country_slugs = set()
    # region items: list of (cache_key, country_slug, path_segments_up_to_here)
    missing_region_items = []
    seen_region_keys = set()

    for entry in osmand_files:
        parsed = parse_filename(entry["fileName"], continent_suffix_map)
        if parsed is None or parsed["is_world_special"]:
            continue  # World_* variants are curated manually in specialFiles, not via AI

        slug = parsed["country_slug"]
        _, resolved = resolve_country(countries, slug)
        if resolved is None and slug not in seen_country_slugs:
            missing_country_slugs.append(slug)
            seen_country_slugs.add(slug)

        if parsed["path_segments"]:
            for i, key in enumerate(region_prefix_keys(slug, parsed["path_segments"]), start=1):
                if key in regions or key in seen_region_keys:
                    continue
                seen_region_keys.add(key)
                missing_region_items.append((key, slug, parsed["path_segments"][:i]))

    return missing_country_slugs, missing_region_items


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not GEMINI_API_KEY:
        print("[rules] GEMINI_API_KEY is not set, aborting", file=sys.stderr)
        sys.exit(1)

    osmand_files = load_json(OSMAND_DATA_JSON, [])
    rule_data = load_json(TAG_RULE_DATA_JSON, {
        "schemaVersion": 1,
        "continentSuffixMap": {},
        "countries": {},
        "regions": {},
        "specialFiles": {},
    })
    countries = rule_data.setdefault("countries", {})
    regions = rule_data.setdefault("regions", {})

    missing_countries, missing_regions = find_missing_items(osmand_files, rule_data)
    print(f"[rules] {len(missing_countries)} unresolved countr(y/ies), "
          f"{len(missing_regions)} unresolved region level(s)")

    consecutive_failures = [0]
    stopped_early = False

    # --- Resolve missing countries first, so freshly-resolved names are available for
    #     region prompts later in this same run. ---
    for slug in missing_countries:
        prompt = COUNTRY_PROMPT_TEMPLATE.format(slug=slug, continent_list=CONTINENT_LIST_TEXT)
        try:
            result = resolve_item(prompt, f"country '{slug}'", consecutive_failures)
        except ConsecutiveFailureBudgetExhausted:
            stopped_early = True
            break
        if result is None:
            continue
        countries[slug] = {
            "en": result.get("en"),
            "he": result.get("he"),
            "continentEn": result.get("continentEn"),
            "continentHe": result.get("continentHe"),
            "iso2": result.get("iso2"),
            "isRegionNotCountry": bool(result.get("isRegionNotCountry", False)),
            "thematicEmoji": result.get("thematicEmoji"),
            "aliasOf": None,
        }
        save_json(TAG_RULE_DATA_JSON, rule_data)
        print(f"[rules] resolved country '{slug}' -> {countries[slug]['en']}")

    if not stopped_early:
        for key, country_slug, path_prefix in missing_regions:
            resolved_slug, country_entry = resolve_country(countries, country_slug)
            country_en = country_entry.get("en") if country_entry else country_slug
            country_he = country_entry.get("he") if country_entry else country_slug

            leaf_slug = path_prefix[-1]
            full_path = " / ".join(path_prefix)
            parent_context = ""
            if len(path_prefix) > 1:
                parent_key = f"{resolved_slug}:{'/'.join(path_prefix[:-1])}"
                parent = regions.get(parent_key)
                if parent:
                    parent_context = f"(This is a sub-region within {parent['en']}.)"

            prompt = REGION_PROMPT_TEMPLATE.format(
                country_en=country_en,
                country_he=country_he,
                full_path=full_path,
                leaf_slug=leaf_slug,
                parent_context=parent_context,
            )
            try:
                result = resolve_item(prompt, f"region '{key}'", consecutive_failures)
            except ConsecutiveFailureBudgetExhausted:
                stopped_early = True
                break
            if result is None:
                continue
            regions[key] = {"en": result.get("en"), "he": result.get("he")}
            save_json(TAG_RULE_DATA_JSON, rule_data)
            print(f"[rules] resolved region '{key}' -> {regions[key]['en']}")

    save_json(TAG_RULE_DATA_JSON, rule_data)

    if stopped_early:
        print(f"[rules] stopped after {MAX_CONSECUTIVE_FAILURES} consecutive failures - "
              "saved progress so far (this is a normal stopping condition, not an error)")
    print("[rules] done")


if __name__ == "__main__":
    main()
