"""
Map external genre vocabularies to the project's genre vocabulary.

Used for artist-level genre enrichment during the filter_data.py pipeline stage.
Loads genre data from Serkan (550k Spotify artists) and Yamac (1920-2020) datasets,
maps raw Spotify sub-genres to our internal vocabulary via AUDIODB_GENRE_MAP.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from genre_families import GENRE_DEFINITIONS
from paths import SERKAN_GENRE, YAMAC_GENRE, VECTORQL_GENRE
from track_dedup import normalize_artist_name
from utils import AUDIODB_GENRE_MAP

# Valid output genres (keys of GENRE_DEFINITIONS)
_VALID_GENRES = set(GENRE_DEFINITIONS.keys())
_SUBSTRING_MIN_LEN = 3


# Sentinel: non-English locale detected but no dedicated output genre → filter out
_BLOCK = object()

# Compound locale tags → dedicated locale genres.
# None values = block (non-English standalone genres containing English substrings).
_LOCALE_OVERRIDES = {
    # French
    "french hip hop": "french-hip-hop",
    "french rap": "french-hip-hop",
    # German
    "german hip hop": "german-hip-hop",
    "german rap": "german-hip-hop",
    # Japanese / Korean
    "japanese pop": "j-pop",
    "japanese rock": "j-rock",
    "korean pop": "k-pop",
    # Chinese / Taiwanese
    "chinese indie": "cantopop",
    "chinese rock": "cantopop",
    "chinese r&b": "cantopop",
    "chinese alternative": "cantopop",
    "taiwan indie": "cantopop",
    "taiwan pop": "cantopop",
    "taiwan rock": "cantopop",
    "mandarin pop": "cantopop",
    "mandarin rock": "cantopop",
    # Latin (compound tags — override keyword default where needed)
    "latin urban": "latin-urban",
    "latin trap": "latin-urban",
    "latin hip hop": "latin-urban",
    "latin jazz": "salsa",
    "latin rock": "spanish",
    "latin alternative": "spanish",
    "latin soul": "soul",
    "rock en espanol": "spanish",
    "rock en español": "spanish",
    "rock independant francais": "french",
    "reggaeton colombiano": "latin-urban",
    "reggaeton flow": "latin-urban",
    # Brazilian / Portuguese
    "brazilian pop": "samba",
    "brazilian rock": "samba",
    "brazilian indie": "samba",
    "mpb": "samba",
    # Indian (compound tags — override keyword default where needed)
    "indian film": "pop-film",
    "tamil film": "pop-film",
    "desi film": "pop-film",
    # Block: non-English standalone genres that contain English substrings
    "rock nacional": None,
}

# Locales WITH dedicated output genres — only these get positive routing.
_LOCALE_KEYWORDS = {
    # European with dedicated genres
    "french": "french",
    "german": "german",
    "spanish": "spanish",
    "swedish": "swedish",
    # Asian
    "chinese": "cantopop",
    "taiwanese": "cantopop",
    "taiwan": "cantopop",
    "mandarin": "cantopop",
    "korean": "k-pop",
    "japanese": "j-pop",
    # Brazilian
    "brazilian": "samba",
    # South Asian → indian
    "indian": "indian",
    "desi": "indian",
    "tamil": "indian",
    "telugu": "indian",
    "punjabi": "indian",
    "bengali": "indian",
    "pakistani": "indian",
    "nepali": "indian",
    "sri lankan": "indian",
    # Latin American → latin-urban
    "latin": "latin-urban",
    "mexican": "latin-urban",
    "colombian": "latin-urban",
    "argentine": "latin-urban",
    "argentino": "latin-urban",
    "argentina": "latin-urban",
    "argentinian": "latin-urban",
    "peruvian": "latin-urban",
    "chilean": "latin-urban",
    "venezuelan": "latin-urban",
    "ecuadorian": "latin-urban",
    "bolivian": "latin-urban",
    "uruguayan": "latin-urban",
    "paraguayan": "latin-urban",
    "cuban": "latin-urban",
    "puerto rican": "latin-urban",
    "dominican": "latin-urban",
    # Caribbean
    "jamaican": "dancehall",
    # African
    "nigerian": "afrobeat",
    "african": "afrobeat",
    "afro": "afrobeat",
    "south african": "afrobeat",
}

# Non-English locale prefixes to BLOCK from generic genres.
# Only locales WITHOUT a dedicated output genre remain here.
# Locales with matching genres were moved to _LOCALE_KEYWORDS above.
_NON_ENGLISH_PREFIXES = frozenset({
    # Europe (non-English speaking, no dedicated genre)
    "dutch", "belgian", "flemish",
    "italian", "portuguese", "greek", "icelandic",
    "norwegian", "danish", "finnish", "estonian", "latvian", "lithuanian",
    "czech", "slovak", "hungarian", "polish", "romanian",
    "serbian", "croatian", "bosnian", "slovenian", "bulgarian", "yugoslav",
    "ukrainian", "belarusian", "russian",
    "turkish", "georgian", "armenian",
    # Asia (without dedicated genres)
    "indonesian", "thai", "vietnamese", "filipino",
    "malaysian", "malay", "singaporean",
    # Middle East
    "persian", "arab", "arabic", "lebanese", "palestinian", "syrian",
    "israeli", "egyptian", "moroccan",
})

# Generic genre tokens — guards _LOCALE_KEYWORDS from non-music tags
# (e.g. "french cinema" should NOT route to the "french" genre).
# NOT used for _NON_ENGLISH_PREFIXES — those block unconditionally.
_LOCALE_GENERIC_TOKENS = (
    # Core genres
    "pop", "rock", "hip hop", "rap", "metal", "house", "electronic",
    "edm", "dance", "jazz", "blues", "folk", "country", "punk",
    "alternative", "indie", "soul", "r&b", "reggae", "funk",
    "ska", "techno", "trance", "classical", "disco",
    # Extended genres
    "trap", "drill", "grime", "reggaeton", "ambient", "chill",
    "gospel", "worship", "emo", "hardcore", "grunge", "opera",
    "acoustic", "psychedelic", "synthwave", "new wave", "dnb",
    "post-punk", "progressive", "industrial", "downtempo", "trip hop",
    "afrobeat", "afrobeats", "cumbia", "bachata", "dancehall", "dub",
    "breakbeat", "garage", "lo-fi", "phonk", "boom bap",
    "samba", "salsa", "swing", "soundtrack", "film",
)

# ---------------------------------------------------------------------------
# Pre-compiled regex patterns — avoids per-call re.compile / re.search loops
# ---------------------------------------------------------------------------
_NON_ENGLISH_RE = re.compile(
    r"\b(?:" + "|".join(
        re.escape(p) for p in sorted(_NON_ENGLISH_PREFIXES, key=len, reverse=True)
    ) + r")\b"
)

_GENERIC_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _LOCALE_GENERIC_TOKENS) + r")\b"
)

_LOCALE_KEYWORD_RES: dict[str, re.Pattern] = {
    locale: re.compile(rf"\b{re.escape(locale)}\b")
    for locale in _LOCALE_KEYWORDS
}

_AUDIODB_SUBSTRING_RULES: list[tuple[str, re.Pattern, str]] = [
    (key, re.compile(rf"\b{re.escape(key)}\b"), genre)
    for key, genre in AUDIODB_GENRE_MAP.items()
    if len(key) >= _SUBSTRING_MIN_LEN
]


def _map_locale_genre(tag: str):
    """Check if tag is a locale-prefixed genre.

    Returns:
        genre string  – use this dedicated locale genre
        _BLOCK        – non-English locale detected, no dedicated genre → filter out
        None          – no locale pattern matched, continue to AUDIODB_GENRE_MAP
    """
    for key, genre in _LOCALE_OVERRIDES.items():
        if key in tag:
            return genre if genre is not None else _BLOCK

    # Locale keywords (positive routing) — only with a genre token guard
    # to avoid "french cinema" → french
    if _GENERIC_TOKEN_RE.search(tag):
        for locale, genre in _LOCALE_KEYWORDS.items():
            if _LOCALE_KEYWORD_RES[locale].search(tag):
                return genre

    # Non-English prefixes — single compiled regex, no per-prefix loop
    if _NON_ENGLISH_RE.search(tag):
        return _BLOCK

    return None


# Locale output genres — dedicated locale genres always allowed even for blocked artists
_LOCALE_OUTPUT_GENRES = (
    set(_LOCALE_KEYWORDS.values())
    | {v for v in _LOCALE_OVERRIDES.values() if v is not None}
)


def _map_standard_genre(tag: str) -> str | None:
    """Map a tag through _VALID_GENRES and AUDIODB_GENRE_MAP (no locale logic)."""
    if tag in _VALID_GENRES:
        return tag
    if tag in AUDIODB_GENRE_MAP:
        return AUDIODB_GENRE_MAP[tag]
    for _, pattern, genre in _AUDIODB_SUBSTRING_RULES:
        if pattern.search(tag):
            return genre
    return None


def explain_raw_genre(raw_genre: str) -> dict[str, str | None]:
    """Explain how a single raw genre tag was resolved.

    Returns keys:
      - tag: normalized input tag
      - mapped_genre: mapped output genre (or None)
      - reason: exact-valid | exact-map | locale-route | locale-block | substring:<key> | none
    """
    tag = (raw_genre or "").lower().strip()
    if not tag:
        return {"tag": tag, "mapped_genre": None, "reason": "none"}

    if tag in _VALID_GENRES:
        return {"tag": tag, "mapped_genre": tag, "reason": "exact-valid"}

    locale_result = _map_locale_genre(tag)
    if locale_result is _BLOCK:
        return {"tag": tag, "mapped_genre": None, "reason": "locale-block"}
    if locale_result is not None:
        return {"tag": tag, "mapped_genre": locale_result, "reason": "locale-route"}

    if tag in AUDIODB_GENRE_MAP:
        return {"tag": tag, "mapped_genre": AUDIODB_GENRE_MAP[tag], "reason": "exact-map"}

    for key, pattern, genre in _AUDIODB_SUBSTRING_RULES:
        if pattern.search(tag):
            return {"tag": tag, "mapped_genre": genre, "reason": f"substring:{key}"}

    return {"tag": tag, "mapped_genre": None, "reason": "none"}


def map_raw_genre(raw_genre: str) -> str | None:
    """Map a single raw genre string to our vocabulary. Returns None if no match."""
    tag = raw_genre.lower().strip()
    if not tag:
        return None

    if tag in _VALID_GENRES:
        return tag

    locale_result = _map_locale_genre(tag)
    if locale_result is _BLOCK:
        return None
    if locale_result is not None:
        return locale_result

    return _map_standard_genre(tag)


def map_artist_tags(tags: list[str]):
    """Map a list of artist tags to a single genre (first match wins).

    Locale tags return immediately (they're special).
    Once any tag triggers _BLOCK (non-English locale detected), subsequent tags
    are only allowed to match dedicated locale genres — generic genres are skipped.
    The first successfully mapped non-locale tag determines the genre.

    Returns:
        genre string  – matched genre
        _BLOCK        – all tags blocked, no dedicated locale genre found
        None          – no tags matched at all
    """
    blocked = False

    for raw_tag in tags:
        tag = raw_tag.lower().strip()
        if not tag:
            continue

        locale_result = _map_locale_genre(tag)
        if locale_result is _BLOCK:
            blocked = True
            continue
        if locale_result is not None:
            return locale_result

        genre = _map_standard_genre(tag)
        if genre:
            if blocked and genre not in _LOCALE_OUTPUT_GENRES:
                continue
            return genre

    return _BLOCK if blocked else None


def explain_artist_tags(tags: list[str]) -> dict[str, object]:
    """Return a structured explanation of artist-level tag mapping."""
    blocked = False
    details: list[dict[str, object]] = []

    for raw_tag in tags:
        tag = (raw_tag or "").lower().strip()
        if not tag:
            continue

        locale_result = _map_locale_genre(tag)
        if locale_result is _BLOCK:
            blocked = True
            details.append({"tag": tag, "status": "blocked-locale", "mapped": None})
            continue
        if locale_result is not None:
            details.append({"tag": tag, "status": "locale-route", "mapped": locale_result})
            return {
                "result": locale_result,
                "blocked": blocked,
                "details": details,
            }

        mapped = _map_standard_genre(tag)
        if mapped:
            if blocked and mapped not in _LOCALE_OUTPUT_GENRES:
                details.append({"tag": tag, "status": "blocked-after-locale", "mapped": mapped})
                continue
            details.append({"tag": tag, "status": "first-match", "mapped": mapped})
            return {"result": mapped, "blocked": blocked, "details": details}
        else:
            details.append({"tag": tag, "status": "no-match", "mapped": None})

    return {"result": _BLOCK if blocked else None, "blocked": blocked, "details": details}


def _parse_genres_list(raw: str | None) -> list[str]:
    """Parse a Python list-repr string like \"['groove metal', 'metal']\" into a list of strings."""
    if not raw or not isinstance(raw, str):
        return []
    stripped = raw.strip()
    if stripped in ("[]", ""):
        return []
    # Remove surrounding brackets
    inner = stripped.lstrip("[").rstrip("]")
    # Split on comma, strip quotes and whitespace from each item
    tags = []
    for item in inner.split(","):
        cleaned = item.strip().strip("'").strip('"').strip()
        if cleaned:
            tags.append(cleaned)
    return tags


def load_artist_genre_lookup(*, return_blocked: bool = False):
    """
    Load preprocessed artist genre parquets and build a normalized_artist_name → genre lookup.

    When the same normalized name appears across sources, the entry with
    highest popularity wins.
    """
    # Collect candidates per normalized artist from all sources.
    # Value shape: list[(genre, popularity)]
    candidates: dict[str, list[tuple[str, int]]] = {}
    blocked_artists: set[str] = set()

    for path in [SERKAN_GENRE, YAMAC_GENRE, VECTORQL_GENRE]:
        if not path.exists():
            print(f"Genre source not found: {path}")
            continue

        df = pl.read_parquet(path)
        for row in df.iter_rows(named=True):
            name = row.get("name")
            if not name:
                continue
            norm_name = normalize_artist_name(str(name))

            tags = row.get("genres") or []
            pop = row.get("popularity") or 0

            genre = map_artist_tags(tags)

            # Fallback: Serkan main_genre → our vocabulary (but NOT if blocked)
            if genre is _BLOCK:
                blocked_artists.add(norm_name)
                continue
            if not genre:
                fallback = row.get("fallback")
                if fallback and isinstance(fallback, str):
                    genre = _map_standard_genre(fallback.strip().lower())

            if not genre:
                continue

            candidates.setdefault(norm_name, []).append((genre, int(pop or 0)))

    lookup: dict[str, str] = {}
    for norm_name, rows in candidates.items():
        # If any source row for this artist triggered locale block,
        # only allow dedicated locale output genres for this artist.
        if norm_name in blocked_artists:
            rows = [r for r in rows if r[0] in _LOCALE_OUTPUT_GENRES]
            if not rows:
                continue

        # Pick highest popularity candidate, deterministic tiebreak by genre name.
        rows = sorted(rows, key=lambda item: (-item[1], item[0]))
        lookup[norm_name] = rows[0][0]

    if return_blocked:
        return lookup, blocked_artists
    return lookup


def build_artist_genre_map(
    df: pl.DataFrame,
    *,
    override: bool = False,
    locked_artists: set[str] | None = None,
    lookup: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a mapping of artist_name -> genre for rows in the DataFrame."""
    lookup = lookup or load_artist_genre_lookup()
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

    lookup, blocked_norms = load_artist_genre_lookup(return_blocked=True)
    name_to_genre = build_artist_genre_map(
        df,
        override=override,
        locked_artists=locked_artists,
        lookup=lookup,
    )

    if not name_to_genre:
        if verbose:
            print("No matches found in external genre lookup.")
        return df

    df = apply_artist_genre_map(df, name_to_genre, override=override)

    # In override mode, actively honor locale-blocked artists by nulling their genres
    # unless they are locked OR their genre is a dedicated locale output genre
    # (the lookup already resolves blocked artists to locale genres correctly).
    if override and blocked_norms and "artist_name" in df.columns:
        locked = set(locked_artists or [])
        blocked_names = [
            name for name in df["artist_name"].drop_nulls().unique().to_list()
            if name not in locked and normalize_artist_name(str(name)) in blocked_norms
        ]
        if blocked_names:
            locale_genres = list(_LOCALE_OUTPUT_GENRES)
            df = df.with_columns(
                pl.when(
                    pl.col("artist_name").is_in(blocked_names)
                    & ~pl.col("genre").is_in(locale_genres)
                )
                .then(pl.lit(None).cast(pl.String))
                .otherwise(pl.col("genre"))
                .alias("genre")
            )

    null_after = df.filter(pl.col("genre").is_null()).height
    enriched = null_before - null_after
    action = "overridden" if override else "enriched"

    print(f"Genre enrichment: {enriched:,} tracks {action} ({null_before:,} null -> {null_after:,} null)")
    if verbose and name_to_genre:
        print(f"  Matched {len(name_to_genre):,} unique artists from external data")

    return df


if __name__ == "__main__":
    lookup = load_artist_genre_lookup()
    print(f"\nArtist genre lookup: {len(lookup):,} artists mapped")

    # Coverage by genre
    genre_counts: dict[str, int] = {}
    for genre in lookup.values():
        genre_counts[genre] = genre_counts.get(genre, 0) + 1

    print(f"\nTop 20 genres by artist count:")
    for genre, count in sorted(genre_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {genre:<25s} {count:>6,}")

    print(f"\nTotal genres used: {len(genre_counts)}")
