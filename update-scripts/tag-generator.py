#!/usr/bin/env python3
"""
tag-generator.py  (file 2 of 2 - pure logic, no AI calls, no network access)
=============================================================================
Rebuilds data/mapsTags.json from scratch on every run, purely by looking up each file's
geography in data/tag-rule-data.json. No network calls, no AI - fast, free, and fully
deterministic, so it always stays in sync with whatever is currently in tag-rule-data.json
(including manual edits).

Runs even while OsmAnd file uploads are still in progress in the same workflow run - unlike
the AI step (tag-rule-generator.py), there's no cost or staleness risk to regenerating tags
from whatever is currently known, so there's no reason to skip it.

--- Schema ---
Each entry in mapsTags.json looks like:
  {
    "fileName": "Canada_british-columbia_alberni-clayoquot_northamerica_2.obf",
    "geo": [
      {"en": "North America", "he": "צפון אמריקה"},
      {"en": "Canada", "he": "קנדה"},
      {"en": "British Columbia", "he": "קולומביה הבריטית"},
      {"en": "Alberni-Clayoquot", "he": "אלברני-קלייקווט"}
    ],
    "emoji": "🇨🇦"
  }

"geo" is an ordered array from broadest to most specific (continent -> country -> region ->
sub-region -> ...), with as many levels as are actually known for that file - there is no
fixed length and no fixed field names, so a file can have 1, 2, 3, 4+ levels as needed instead
of being forced into a rigid continent/country/city shape. A level is only included if it is
actually known; nothing is ever included as null/empty, and nothing known is ever dropped.

If tag-rule-data.json is missing an entry for some file (e.g. tag-rule-generator.py hasn't
resolved it yet), this script still produces the best partial "geo" array it can (falling back
to continentSuffixMap for the continent level) rather than skipping the file - so mapsTags.json
is never more incomplete than it has to be, even when the AI step is behind.
"""

import json
import sys
from pathlib import Path

from osmand_filename import parse_filename, region_prefix_keys, resolve_country, flag_emoji_from_iso2

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

OSMAND_DATA_JSON = DATA_DIR / "osmand-data.json"
MAPS_TAGS_JSON = DATA_DIR / "mapsTags.json"
TAG_RULE_DATA_JSON = DATA_DIR / "tag-rule-data.json"

FALLBACK_EMOJI = "🗂️"


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


def build_tag_for_file(file_name: str, rule_data: dict):
    continent_suffix_map = rule_data.get("continentSuffixMap", {})
    countries = rule_data.get("countries", {})
    regions = rule_data.get("regions", {})
    special_files = rule_data.get("specialFiles", {})

    parsed = parse_filename(file_name, continent_suffix_map)
    if parsed is None:
        return {"fileName": file_name, "geo": [], "emoji": FALLBACK_EMOJI}

    # --- World_* special files (no continent-suffix segment) ---
    if parsed["is_world_special"]:
        special = special_files.get(parsed["world_remainder"])
        if special:
            return {
                "fileName": file_name,
                "geo": [{"en": special["continentEn"], "he": special["continentHe"]}],
                "emoji": special.get("emoji", "🌐"),
            }
        return {
            "fileName": file_name,
            "geo": [{"en": "World", "he": "עולם"}],
            "emoji": "🌐",
        }

    # --- Ordinary country files ---
    resolved_slug, country_entry = resolve_country(countries, parsed["country_slug"])

    if country_entry is None:
        # Not in the rule table yet - best-effort continent-only guess, nothing invented.
        suffix = continent_suffix_map.get(parsed["continent_suffix"]) if parsed["continent_suffix"] else None
        geo = [{"en": suffix["en"], "he": suffix["he"]}] if suffix else []
        return {"fileName": file_name, "geo": geo, "emoji": FALLBACK_EMOJI}

    geo = [{"en": country_entry["continentEn"], "he": country_entry["continentHe"]}]

    if not country_entry.get("isRegionNotCountry"):
        geo.append({"en": country_entry["en"], "he": country_entry["he"]})

    if parsed["path_segments"]:
        for key in region_prefix_keys(resolved_slug, parsed["path_segments"]):
            region = regions.get(key)
            if not region:
                break  # stop at the first unresolved level - keep the array a clean prefix
            geo.append({"en": region["en"], "he": region["he"]})

    iso2 = country_entry.get("iso2")
    if iso2:
        emoji = flag_emoji_from_iso2(iso2)
    elif country_entry.get("thematicEmoji"):
        emoji = country_entry["thematicEmoji"]
    else:
        emoji = FALLBACK_EMOJI

    return {"fileName": file_name, "geo": geo, "emoji": emoji}


def main():
    osmand_files = load_json(OSMAND_DATA_JSON, [])
    rule_data = load_json(TAG_RULE_DATA_JSON, {})

    if not rule_data:
        print("[tags] tag-rule-data.json is missing or empty - producing best-effort "
              "fallback tags only", file=sys.stderr)

    tags = [build_tag_for_file(entry["fileName"], rule_data) for entry in osmand_files]
    save_json(MAPS_TAGS_JSON, tags)

    fully_resolved = sum(1 for t in tags if len(t["geo"]) >= 2)
    print(f"[tags] rebuilt {len(tags)} tag entries "
          f"({fully_resolved} with country-level or deeper, "
          f"{len(tags) - fully_resolved} continent-only/fallback)")


if __name__ == "__main__":
    main()
