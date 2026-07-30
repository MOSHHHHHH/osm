"""
osmand_filename.py
===================
Shared, dependency-free filename parsing for OsmAnd .obf files. Both tag-rule-generator.py
(fills in missing rule data) and tag-generator.py (builds mapsTags.json from that rule data)
import this so there is exactly one definition of how a filename decomposes - avoiding any
risk of the two scripts silently disagreeing.

OsmAnd's naming convention (observed from download.osmand.net/list.php, and expected to keep
holding for future additions since it is OsmAnd's own long-standing generation scheme):

    {Country}[_{Region}[_{Subregion}...]]_{continent-suffix}_{formatVersion}.obf

- The first underscore-separated segment is always the country (or, for a handful of special
  cases, the literal word "World").
- The last segment before the file extension is usually a numeric map-format version (e.g. the
  "2" in "..._2.obf") - stripped generically (any trailing purely-numeric segment), so a future
  OsmAnd format bump (e.g. "_3") keeps working without a code change.
- The segment before that is usually one of a small, fixed set of continent-suffix words
  (asia, europe, africa, northamerica, centralamerica, southamerica, australia-oceania) - if the
  last remaining segment matches one of these, it is treated as the continent suffix and
  excluded from the region path. "World_*" files have no continent suffix segment at all.
- Everything between the country and the continent suffix is the region/subregion path.
"""

from pathlib import Path


def _strip_extension_and_version(file_name: str):
    """Returns the underscore-separated segments of a filename, with the .obf extension and
    any trailing purely-numeric "format version" segment removed."""
    base = file_name
    if base.lower().endswith(".obf"):
        base = base[:-4]
    parts = base.split("_")
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return parts


def parse_filename(file_name: str, continent_suffix_map: dict):
    """Returns a dict describing the filename's structure:
    {
      "country_slug": str (lowercased),
      "path_segments": [str, ...] (lowercased, the region/subregion path, may be empty),
      "continent_suffix": str or None (lowercased, only set if a known suffix was found),
      "is_world_special": bool,
      "world_remainder": str or None (only set when is_world_special is True; the remaining
                                       segments joined with "_", e.g. "basemap", "seamarks"),
    }
    Returns None if the filename has no usable segments at all (should not happen in practice).
    """
    parts = _strip_extension_and_version(Path(file_name).name)
    if not parts:
        return None

    country_slug = parts[0].lower()
    rest = parts[1:]

    if country_slug == "world":
        return {
            "country_slug": "world",
            "path_segments": [],
            "continent_suffix": None,
            "is_world_special": True,
            "world_remainder": "_".join(seg.lower() for seg in rest) if rest else "",
        }

    path_segments = [seg.lower() for seg in rest]
    continent_suffix = None
    if path_segments and path_segments[-1] in continent_suffix_map:
        continent_suffix = path_segments[-1]
        path_segments = path_segments[:-1]

    return {
        "country_slug": country_slug,
        "path_segments": path_segments,
        "continent_suffix": continent_suffix,
        "is_world_special": False,
        "world_remainder": None,
    }


def region_cache_key(country_slug: str, path_segments: list) -> str:
    """The cache key used in tag-rule-data.json's "regions" table for the FULL path.
    Kept for backward compatibility; prefer region_prefix_keys for multi-level resolution."""
    return f"{country_slug}:{'/'.join(path_segments)}"


def region_prefix_keys(country_slug: str, path_segments: list):
    """Returns one cache key per prefix length of path_segments, in order, e.g. for
    path_segments=["british-columbia","alberni-clayoquot"] returns:
      ["canada:british-columbia", "canada:british-columbia/alberni-clayoquot"]
    This lets each level of a deeply-nested file (region, then sub-region, then...) be
    resolved and cached independently, supporting arbitrarily many geo levels."""
    keys = []
    for i in range(1, len(path_segments) + 1):
        keys.append(f"{country_slug}:{'/'.join(path_segments[:i])}")
    return keys


def resolve_country(countries: dict, country_slug: str, max_alias_depth: int = 5):
    """Follows aliasOf chains and returns (resolved_slug, entry) or (country_slug, None) if
    the slug is not present in the table at all."""
    slug = country_slug
    seen = set()
    for _ in range(max_alias_depth):
        entry = countries.get(slug)
        if entry is None:
            return slug, None
        alias = entry.get("aliasOf")
        if not alias or alias in seen:
            return slug, entry
        seen.add(slug)
        slug = alias
    return slug, countries.get(slug)


def flag_emoji_from_iso2(iso2: str) -> str:
    """Converts a 2-letter ISO 3166-1 alpha-2 code into its flag emoji (two Unicode
    Regional Indicator Symbols)."""
    offset = 0x1F1E6 - ord("A")
    return "".join(chr(ord(c) + offset) for c in iso2.upper())
