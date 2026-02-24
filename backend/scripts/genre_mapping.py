"""
Map external genre vocabularies to the project's 82-genre vocabulary.

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
from paths import SERKAN_ARTISTS_CSV, YAMAC_ARTISTS_CSV
from track_dedup import normalize_artist_name
from utils import AUDIODB_GENRE_MAP

# Map Serkan main_genre (10 broad categories) → our vocabulary
SERKAN_MAIN_GENRE_MAP = {
    "Rock": "rock",
    "Electronic": "electronic",
    "Pop": "pop",
    "Hip-Hop": "hip-hop",
    "Folk": "folk",
    "Classical": "classical",
    "R&B": "soul",
    "Country": "country",
    "Jazz": "jazz",
    "Blues": "blues",
}

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
    # Latin (compound tags → dedicated locale genres)
    "latin urban": "latin-urban",
    "latin trap": "latin-urban",
    "latin hip hop": "latin-urban",
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
    # Block: non-English standalone genres that contain English substrings
    "rock nacional": None,
}

# Locales WITH dedicated output genres — only these get positive routing.
_LOCALE_KEYWORDS = {
    # Original locale keywords
    "french": "french",
    "german": "german",
    "spanish": "spanish",
    "swedish": "swedish",
    "indian": "indian",
    # Asian / Brazilian — added during genre system build-out
    "chinese": "cantopop",
    "taiwanese": "cantopop",
    "taiwan": "cantopop",
    "mandarin": "cantopop",
    "korean": "k-pop",
    "japanese": "j-pop",
    "brazilian": "samba",
}

# Non-English locale prefixes to BLOCK from generic genres for now.
# English-speaking locales (irish, scottish, welsh, australian, canadian, etc.) absent.
# Any tag containing one of these prefixes is blocked regardless of what follows for now
_NON_ENGLISH_PREFIXES = frozenset({
    # Europe (non-English speaking)
    "dutch", "belgian", "flemish",
    "italian", "portuguese", "greek", "icelandic",
    "norwegian", "danish", "finnish", "estonian", "latvian", "lithuanian",
    "czech", "slovak", "hungarian", "polish", "romanian",
    "serbian", "croatian", "bosnian", "slovenian", "bulgarian", "yugoslav",
    "ukrainian", "belarusian", "russian",
    "turkish", "georgian", "armenian",
    # Latin America
    "latin", "mexican", "argentine", "argentino", "argentina", "argentinian",
    "colombian", "peruvian", "chilean", "venezuelan",
    "ecuadorian", "bolivian", "uruguayan", "paraguayan",
    "cuban", "puerto rican", "dominican",
    # Caribbean
    "jamaican",
    # Asia (without dedicated genres)
    "indonesian", "thai", "vietnamese", "filipino",
    "malaysian", "malay", "singaporean",
    # South Asia (without dedicated genres — indian HAS one)
    "desi", "pakistani", "nepali", "sri lankan", "bengali", "tamil", "telugu", "punjabi",
    # Middle East / Africa
    "persian", "arab", "arabic", "lebanese", "palestinian", "syrian",
    "israeli", "egyptian", "moroccan",
    "nigerian", "south african", "african", "afro",
})

# Generic genre tokens — guards _LOCALE_KEYWORDS from non-music tags
# (e.g. "french cinema" should NOT route to the "french" genre).
# NOT used for _NON_ENGLISH_PREFIXES — those block unconditionally.
_LOCALE_GENERIC_TOKENS = (
    "pop", "rock", "hip hop", "rap", "metal", "house", "electronic",
    "edm", "dance", "jazz", "blues", "folk", "country", "punk",
    "alternative", "indie", "soul", "r&b", "reggae", "funk",
    "ska", "techno", "trance", "classical", "disco",
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

_AUDIODB_SUBSTRING_RES: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"\b{re.escape(key)}\b"), genre)
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
    for pattern, genre in _AUDIODB_SUBSTRING_RES:
        if pattern.search(tag):
            return genre
    return None


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
    """Map a list of artist tags to a single genre, with per-artist blocking.

    Once any tag triggers _BLOCK (non-English locale detected), subsequent tags
    are only allowed to match dedicated locale genres — generic genres are skipped.

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


def load_artist_genre_lookup() -> dict[str, str]:
    """
    Load external artist CSVs and build a normalized_artist_name → genre lookup.

    Yamac entries take priority over Serkan for the same artist name.
    """
    lookup: dict[str, str] = {}

    # --- Yamac (priority source) ---
    if YAMAC_ARTISTS_CSV.exists():
        df = pl.read_csv(YAMAC_ARTISTS_CSV, infer_schema_length=1000)
        for row in df.iter_rows(named=True):
            name = row.get("name")
            if not name:
                continue
            norm_name = normalize_artist_name(str(name))
            if norm_name in lookup:
                continue

            genre = map_artist_tags(_parse_genres_list(row.get("genres")))
            if genre and genre is not _BLOCK:
                lookup[norm_name] = genre
    else:
        print(f"Yamac artists CSV not found: {YAMAC_ARTISTS_CSV}")

    # --- Serkan (fallback source) ---
    if SERKAN_ARTISTS_CSV.exists():
        df = pl.read_csv(SERKAN_ARTISTS_CSV, infer_schema_length=1000)
        for row in df.iter_rows(named=True):
            name = row.get("name")
            if not name:
                continue
            norm_name = normalize_artist_name(str(name))
            if norm_name in lookup:
                continue

            # Try raw sub-genres first (with per-artist blocking)
            genre = map_artist_tags(_parse_genres_list(row.get("genres")))

            # Fall back to main_genre — but NOT if tags were blocked
            # (Tipe-X fix: blocked locale tags + main_genre "Rock" → skip)
            if genre is _BLOCK:
                continue
            if not genre:
                main = row.get("main_genre")
                if main and isinstance(main, str):
                    genre = SERKAN_MAIN_GENRE_MAP.get(main.strip())

            if genre:
                lookup[norm_name] = genre
    else:
        print(f"Serkan artists CSV not found: {SERKAN_ARTISTS_CSV}")

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

    name_to_genre = build_artist_genre_map(
        df,
        override=override,
        locked_artists=locked_artists,
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
