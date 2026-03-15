"""
Map external genre tags to the internal Vibe genre vocabulary.

Two-pass architecture:
  Pass 1 (this module): Tag mapping returns (genre, tag_lang).
    - Locale-compound tags get the locale stripped, genre kept, language recorded.
    - No blocking — every artist that has a mappable tag gets a genre.
  Pass 2 (process_data.py): Language resolution cascade per artist.

Used by filter-time artist genre enrichment.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from genre_families import GENRE_DEFINITIONS
from genre_locale_config import (
    LOCALE_TO_LANG as _LOCALE_TO_LANG,
    LOCALE_OVERRIDES as _LOCALE_OVERRIDES,
    LOCALE_GENRE_KEYWORDS as _LOCALE_GENRE_KEYWORDS,
    LOCALE_GENERIC_TOKENS as _LOCALE_GENERIC_TOKENS,
)
from paths import SERKAN_GENRE, YAMAC_GENRE, VECTORQL_GENRE
from track_dedup import normalize_artist_name
from utils import AUDIODB_GENRE_MAP

# Valid output genre names
_VALID_GENRES = set(GENRE_DEFINITIONS.keys())


# ---------------------------------------------------------------------------
# Locale → ISO language code mapping (merged from old _LOCALE_KEYWORDS +
# _NON_ENGLISH_PREFIXES).  Value is an ISO 639-1 code, or None when the
# locale is ambiguous (multi-lingual country).
# ---------------------------------------------------------------------------
# Pre-compiled regexes
_GENERIC_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _LOCALE_GENERIC_TOKENS) + r")\b"
)

_LOCALE_ALL_RE = re.compile(
    r"\b(?:" + "|".join(
        re.escape(p) for p in sorted(_LOCALE_TO_LANG, key=len, reverse=True)
    ) + r")\b"
)

_LOCALE_GENRE_KEYWORD_RES: dict[str, re.Pattern] = {
    locale: re.compile(rf"\b{re.escape(locale)}\b")
    for locale in _LOCALE_GENRE_KEYWORDS
}

# Safe prefixes to strip before exact mapping; longest first.
_SAFE_PREFIXES: tuple[str, ...] = tuple(sorted([
    "australian", "canadian", "british", "american", "uk",
    "scottish", "irish", "welsh", "new zealand", "nz", "aussie", "aus",
    "modern", "classic", "contemporary", "old school", "old-school",
    "neo", "nu", "new",
    "deep", "dark", "melodic", "atmospheric", "raw",
    "technical", "symphonic", "brutal", "epic",
], key=len, reverse=True))

# Last-resort substring rules for unambiguous multi-word compounds.
_COMPOUND_SUBSTRING_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"\b{re.escape(k)}\b"), v)
    for k, v in {
        "death metal": "death-metal",
        "black metal": "black-metal",
        "doom metal": "metal",
        "stoner metal": "metal",
        "sludge metal": "metal",
        "speed metal": "metal",
        "power metal": "heavy-metal",
        "groove metal": "groove",
        "thrash metal": "metal",
        "folk metal": "heavy-metal",
        "viking metal": "heavy-metal",
        "gothic metal": "metal",
        "symphonic metal": "prog-metal",
        "progressive metal": "prog-metal",
        "industrial metal": "industrial-metal",
        "hard rock": "hard-rock",
        "blues rock": "blues",
        "folk rock": "folk",
        "noise rock": "alt-rock",
        "garage rock": "garage",
        "psychedelic rock": "psych-rock",
        "progressive rock": "progressive-rock",
        "post-punk": "punk-rock",
        "post-rock": "post-rock",
        "drum and bass": "drum-and-bass",
        "post-hardcore": "post-hardcore",
        "uk grime": "grime",
        "instrumental grime": "grime",
        "alternative hip hop": "hip-hop",
        "experimental hip hop": "hip-hop",
        "industrial hip hop": "hip-hop",
        "pop rap": "hip-hop",
        "southern hip hop": "hip-hop",
        "atl hip hop": "hip-hop",
        "miami hip hop": "hip-hop",
        "dirty south rap": "hip-hop",
        "country rap": "hip-hop",
        "country hip hop": "hip-hop",
        "tech house": "house",
        "future house": "house",
        "progressive house": "progressive-house",
        "electro house": "edm",
        "progressive electro house": "edm",
        "minimal techno": "minimal-techno",
        "modern reggae": "reggae",
        "virgin islands reggae": "reggae",
        "neo classical metal": "prog-metal",
        "gothic symphonic metal": "prog-metal",
    }.items()
]


def _map_locale_tag(tag: str) -> tuple[str | None, str | None]:
    """Resolve locale-specific tags.

    Returns:
        (genre, tag_lang) — genre and/or language signal from this tag.
        (None, None) if tag has no locale content.
    """
    # Explicit phrase overrides first
    for key, (genre, lang) in _LOCALE_OVERRIDES.items():
        if key in tag:
            return genre, lang

    # Positive locale routing requires a genre token guard.
    if _GENERIC_TOKEN_RE.search(tag):
        for locale, genre in _LOCALE_GENRE_KEYWORDS.items():
            if _LOCALE_GENRE_KEYWORD_RES[locale].search(tag):
                lang = _LOCALE_TO_LANG.get(locale)
                return genre, lang

    # Check for any locale keyword — extract language but let genre come from
    # standard mapping (the tag contains a locale adjective but paired with a
    # genre token that should be mapped normally).
    m = _LOCALE_ALL_RE.search(tag)
    if m:
        locale_word = m.group(0)
        lang = _LOCALE_TO_LANG.get(locale_word)
        # Try to extract the genre portion after stripping the locale word
        remainder = tag.replace(locale_word, "").strip()
        remainder = re.sub(r"\s+", " ", remainder).strip()
        if remainder:
            genre = _map_standard_genre(remainder)
            if genre:
                return genre, lang
        # No genre extracted from remainder — just return language signal
        return None, lang

    return None, None


def _map_standard_genre(tag: str) -> str | None:
    """Map using exact match, direct map, safe-prefix strip, then compound fallback."""
    if tag in _VALID_GENRES:
        return tag
    if tag in AUDIODB_GENRE_MAP:
        return AUDIODB_GENRE_MAP[tag]
    for prefix in _SAFE_PREFIXES:
        if tag.startswith(prefix + " "):
            remainder = tag[len(prefix) + 1:]
            if remainder in _VALID_GENRES:
                return remainder
            if remainder in AUDIODB_GENRE_MAP:
                return AUDIODB_GENRE_MAP[remainder]
    for pattern, genre in _COMPOUND_SUBSTRING_RULES:
        if pattern.search(tag):
            return genre
    return None


def explain_raw_genre(raw_genre: str) -> dict[str, object]:
    """Return a trace for how one raw genre tag was resolved."""
    tag = (raw_genre or "").lower().strip()
    if not tag:
        return {"tag": tag, "mapped_genre": None, "tag_lang": None, "reason": "none"}

    if tag in _VALID_GENRES:
        return {"tag": tag, "mapped_genre": tag, "tag_lang": None, "reason": "exact-valid"}

    genre, lang = _map_locale_tag(tag)
    if genre is not None:
        return {"tag": tag, "mapped_genre": genre, "tag_lang": lang, "reason": "locale-route"}
    if lang is not None:
        return {"tag": tag, "mapped_genre": None, "tag_lang": lang, "reason": "locale-lang-only"}

    if tag in AUDIODB_GENRE_MAP:
        return {"tag": tag, "mapped_genre": AUDIODB_GENRE_MAP[tag], "tag_lang": None, "reason": "exact-map"}

    for prefix in _SAFE_PREFIXES:
        if tag.startswith(prefix + " "):
            remainder = tag[len(prefix) + 1:]
            if remainder in _VALID_GENRES:
                return {"tag": tag, "mapped_genre": remainder, "tag_lang": None, "reason": f"prefix-strip:{prefix}->exact-valid"}
            if remainder in AUDIODB_GENRE_MAP:
                return {"tag": tag, "mapped_genre": AUDIODB_GENRE_MAP[remainder], "tag_lang": None, "reason": f"prefix-strip:{prefix}->exact-map"}

    for pattern, genre in _COMPOUND_SUBSTRING_RULES:
        if pattern.search(tag):
            return {"tag": tag, "mapped_genre": genre, "tag_lang": None, "reason": f"compound:{pattern.pattern}"}

    return {"tag": tag, "mapped_genre": None, "tag_lang": None, "reason": "none"}


def map_raw_genre(raw_genre: str) -> str | None:
    """Map a single raw genre string to our vocabulary. Returns None if no match."""
    tag = raw_genre.lower().strip()
    if not tag:
        return None

    if tag in _VALID_GENRES:
        return tag

    genre, _lang = _map_locale_tag(tag)
    if genre is not None:
        return genre

    return _map_standard_genre(tag)


def map_artist_tags(tags: list[str]) -> tuple[str | None, str | None]:
    """Map a list of artist tags to a single (genre, tag_lang) tuple.

    Locale-routed genres win when there is a strong locale signal
    (>= 2 locale tags or no standard alternatives).  A single locale
    tag among many standard tags is treated as noise.

    Returns:
        (genre, tag_lang) — the best genre and any language signal from tags.
        genre may be None if no tag maps. tag_lang may be None.
    """
    first_standard: str | None = None
    first_locale_genre: str | None = None
    all_langs: list[str] = []
    locale_count = 0
    standard_count = 0
    first_mapped_is_locale: bool | None = None

    for raw_tag in tags:
        tag = raw_tag.lower().strip()
        if not tag:
            continue

        genre, lang = _map_locale_tag(tag)
        if lang is not None:
            all_langs.append(lang)

        if genre is not None:
            locale_count += 1
            if first_locale_genre is None:
                first_locale_genre = genre
            if first_mapped_is_locale is None:
                first_mapped_is_locale = True
            continue

        std_genre = _map_standard_genre(tag)
        if std_genre:
            standard_count += 1
            if first_standard is None:
                first_standard = std_genre
            if first_mapped_is_locale is None:
                first_mapped_is_locale = False

    # Determine winning genre
    if first_locale_genre is not None and (
        locale_count >= 2 or standard_count == 0 or first_mapped_is_locale
    ):
        result_genre = first_locale_genre
    elif first_standard is not None:
        result_genre = first_standard
    elif first_locale_genre is not None:
        result_genre = first_locale_genre
    else:
        result_genre = None

    # Determine tag_lang: use the most common non-None lang from tags
    tag_lang: str | None = None
    if all_langs:
        from collections import Counter
        lang_counts = Counter(l for l in all_langs if l is not None)
        if lang_counts:
            tag_lang = lang_counts.most_common(1)[0][0]

    return result_genre, tag_lang


def explain_artist_tags(tags: list[str]) -> dict[str, object]:
    """Return a structured explanation of artist-level tag mapping."""
    first_standard: str | None = None
    first_locale_genre: str | None = None
    locale_count = 0
    standard_count = 0
    first_mapped_is_locale: bool | None = None
    details: list[dict[str, object]] = []
    all_langs: list[str] = []

    for raw_tag in tags:
        tag = (raw_tag or "").lower().strip()
        if not tag:
            continue

        genre, lang = _map_locale_tag(tag)
        if lang is not None:
            all_langs.append(lang)

        if genre is not None:
            locale_count += 1
            if first_locale_genre is None:
                first_locale_genre = genre
            if first_mapped_is_locale is None:
                first_mapped_is_locale = True
            details.append({"tag": tag, "status": "locale-route", "mapped": genre, "tag_lang": lang})
            continue

        if lang is not None:
            details.append({"tag": tag, "status": "locale-lang-only", "mapped": None, "tag_lang": lang})
            # Fall through to standard mapping
        
        mapped = _map_standard_genre(tag)
        if mapped:
            standard_count += 1
            if first_standard is None:
                first_standard = mapped
                details.append({"tag": tag, "status": "first-match", "mapped": mapped, "tag_lang": lang})
            else:
                details.append({"tag": tag, "status": "later-match", "mapped": mapped, "tag_lang": lang})
            if first_mapped_is_locale is None:
                first_mapped_is_locale = False
        elif lang is None:
            details.append({"tag": tag, "status": "no-match", "mapped": None, "tag_lang": None})

    # Count genre votes
    votes: dict[str, int] = {}
    for d in details:
        m = d.get("mapped")
        if m:
            votes[m] = votes.get(m, 0) + 1

    # Determine result
    if first_locale_genre is not None and (
        locale_count >= 2 or standard_count == 0 or first_mapped_is_locale
    ):
        result = first_locale_genre
    elif first_standard is not None:
        result = first_standard
    elif first_locale_genre is not None:
        result = first_locale_genre
    else:
        result = None

    # Determine tag_lang
    tag_lang: str | None = None
    if all_langs:
        from collections import Counter
        lang_counts = Counter(l for l in all_langs if l is not None)
        if lang_counts:
            tag_lang = lang_counts.most_common(1)[0][0]

    return {"result": result, "tag_lang": tag_lang, "details": details, "votes": votes}


def _parse_genres_list(raw: str | None) -> list[str]:
    """Parse a Python list-repr string like \"['groove metal', 'metal']\" into a list of strings."""
    if not raw or not isinstance(raw, str):
        return []
    stripped = raw.strip()
    if stripped in ("[]", ""):
        return []
    inner = stripped.lstrip("[").rstrip("]")
    tags = []
    for item in inner.split(","):
        cleaned = item.strip().strip("'").strip('"').strip()
        if cleaned:
            tags.append(cleaned)
    return tags


def load_artist_genre_lookup() -> tuple[dict[str, str], dict[str, str]]:
    """
    Load preprocessed artist genre parquets and build lookups.

    Returns:
        (genre_lookup, lang_lookup) — two dicts keyed by normalized artist name.
        genre_lookup maps to genre string, lang_lookup maps to ISO lang code.

    Sources are checked sequentially in quality order (Yamac → Vectorql → Serkan).
    """
    _tag_cache: dict[tuple, tuple[str | None, str | None]] = {}
    genre_lookup: dict[str, str] = {}
    lang_lookup: dict[str, str] = {}

    for path in [YAMAC_GENRE, VECTORQL_GENRE, SERKAN_GENRE]:
        if not path.exists():
            print(f"Genre source not found: {path}")
            continue

        df = pl.read_parquet(path)

        df = df.with_columns(
            pl.col("name")
            .cast(pl.Utf8)
            .map_elements(normalize_artist_name, return_dtype=pl.Utf8)
            .alias("_norm")
        )
        df = df.filter(pl.col("_norm") != "")

        skip = set(genre_lookup.keys())
        if skip:
            df = df.filter(~pl.col("_norm").is_in(list(skip)))

        if df.is_empty():
            continue

        if "popularity" not in df.columns:
            df = df.with_columns(pl.lit(0).alias("popularity"))

        df = (
            df.with_columns(pl.col("popularity").fill_null(0).cast(pl.Int64).alias("_pop"))
            .sort("_pop", descending=True)
            .unique(subset=["_norm"], keep="first")
            .drop("_pop")
        )

        for row in df.iter_rows(named=True):
            norm_name = row["_norm"]
            tags = row.get("genres") or []
            fallback = row.get("fallback")

            if not tags:
                tags = []

            tags_key = tuple(tags) if isinstance(tags, list) else (tags,)
            if tags_key in _tag_cache:
                genre, tag_lang = _tag_cache[tags_key]
            else:
                genre, tag_lang = map_artist_tags(tags)
                _tag_cache[tags_key] = (genre, tag_lang)

            if not genre and fallback and isinstance(fallback, str):
                genre = _map_standard_genre(fallback.strip().lower())

            if genre:
                genre_lookup[norm_name] = genre
            if tag_lang:
                lang_lookup[norm_name] = tag_lang

    return genre_lookup, lang_lookup


def build_artist_genre_map(
    df: pl.DataFrame,
    *,
    override: bool = False,
    locked_artists: set[str] | None = None,
    lookup: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a mapping of artist_name -> genre for rows in the DataFrame."""
    if lookup is None:
        lookup, _lang = load_artist_genre_lookup()
    locked_artists = set(locked_artists or [])

    if override:
        artist_names = df["artist_name"].unique().to_list()
        if locked_artists:
            artist_names = [name for name in artist_names if name not in locked_artists]
    else:
        artist_names = df.filter(pl.col("genre").is_null())["artist_name"].unique().to_list()

    name_to_genre: dict[str, str] = {}
    for name in artist_names:
        if name is None:
            continue
        norm = normalize_artist_name(str(name))
        genre = lookup.get(norm)
        if genre:
            name_to_genre[name] = genre

    return name_to_genre

def apply_artist_genre_map(
    df: pl.DataFrame,
    name_to_genre: dict[str, str],
    *,
    override: bool = False,
    keep_ext_genre: bool = False,
) -> pl.DataFrame:
    """Apply a name->genre mapping to the DataFrame, optionally preserving _ext_genre."""
    mapping_df = pl.DataFrame({
        "artist_name": list(name_to_genre.keys()),
        "_ext_genre": list(name_to_genre.values()),
    })

    df = df.join(mapping_df, on="artist_name", how="left")
    if override:
        df = df.with_columns(
            pl.when(pl.col("_ext_genre").is_not_null())
            .then(pl.col("_ext_genre"))
            .otherwise(pl.col("genre"))
            .alias("genre")
        )
    else:
        df = df.with_columns(
            pl.when(pl.col("genre").is_null())
            .then(pl.col("_ext_genre"))
            .otherwise(pl.col("genre"))
            .alias("genre")
        )

    if not keep_ext_genre:
        df = df.drop("_ext_genre")

    return df

def enrich_genres(
    df: pl.DataFrame,
    verbose: bool = False,
    override: bool = False,
    locked_artists: set[str] | None = None,
) -> pl.DataFrame:
    """
    Fill null genres in the pipeline DataFrame using external artist genre data.

    Looks up artist_name in the external genre lookup and fills nulls.
    When override=True, replaces ALL genres with external data (not just nulls).
    Returns the DataFrame with enriched genre column.
    """
    null_before = df.filter(pl.col("genre").is_null()).height
    if not override and null_before == 0:
        if verbose:
            print("No null genres to enrich.")
        return df

    genre_lookup, _lang_lookup = load_artist_genre_lookup()
    name_to_genre = build_artist_genre_map(
        df,
        override=override,
        locked_artists=locked_artists,
        lookup=genre_lookup,
    )

    if not name_to_genre:
        if verbose:
            print("No matches found in external genre lookup.")
        return df

    df = apply_artist_genre_map(df, name_to_genre, override=override)

    null_after = df.filter(pl.col("genre").is_null()).height
    enriched = null_before - null_after
    action = "overridden" if override else "enriched"

    print(f"Genre enrichment: {enriched:,} tracks {action} ({null_before:,} null -> {null_after:,} null)")
    if verbose and name_to_genre:
        print(f"  Matched {len(name_to_genre):,} unique artists from external data")

    return df


if __name__ == "__main__":
    genre_lookup, lang_lookup = load_artist_genre_lookup()
    print(f"\nArtist genre lookup: {len(genre_lookup):,} artists mapped")
    print(f"Artist lang lookup:  {len(lang_lookup):,} artists with tag language")

    genre_counts: dict[str, int] = {}
    for genre in genre_lookup.values():
        genre_counts[genre] = genre_counts.get(genre, 0) + 1

    print(f"\nTop 20 genres by artist count:")
    for genre, count in sorted(genre_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {genre:<25s} {count:>6,}")

    print(f"\nTotal genres used: {len(genre_counts)}")

    lang_counts: dict[str, int] = {}
    for lang in lang_lookup.values():
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    print(f"\nTop 10 tag languages:")
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {lang:<10s} {count:>6,}")
