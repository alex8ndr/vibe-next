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
_SUBSTRING_MIN_LEN = 4
_LOCALE_OVERRIDES = {
    "french hip hop": "french-hip-hop",
    "french rap": "french-hip-hop",
    "german hip hop": "german-hip-hop",
    "german rap": "german-hip-hop",
    "japanese pop": "j-pop",
    "japanese rock": "j-rock",
    "korean pop": "k-pop",
}
_LOCALE_KEYWORDS = {
    "french": "french",
    "german": "german",
    "spanish": "spanish",
    "swedish": "swedish",
    "indian": "indian",
}
_LOCALE_GENERIC_TOKENS = (
    "pop",
    "rock",
    "hip hop",
    "rap",
    "metal",
    "house",
    "electronic",
    "edm",
    "dance",
    "jazz",
    "blues",
    "folk",
    "country",
    "punk",
    "alternative",
    "indie",
)

def _token_in_tag(tag: str, token: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", tag) is not None

def _map_locale_genre(tag: str) -> str | None:
    for key, genre in _LOCALE_OVERRIDES.items():
        if key in tag:
            return genre

    if any(_token_in_tag(tag, token) for token in _LOCALE_GENERIC_TOKENS):
        for locale, genre in _LOCALE_KEYWORDS.items():
            if _token_in_tag(tag, locale):
                return genre

    return None


def map_raw_genre(raw_genre: str) -> str | None:
    """Map a single raw genre string to our vocabulary. Returns None if no match."""
    tag = raw_genre.lower().strip()
    if not tag:
        return None

    # Direct match in vocabulary
    if tag in _VALID_GENRES:
        return tag

    # Exact match in AUDIODB_GENRE_MAP
    if tag in AUDIODB_GENRE_MAP:
        return AUDIODB_GENRE_MAP[tag]

    # Locale-aware overrides (prefer language/region tags over broad genres)
    locale_genre = _map_locale_genre(tag)
    if locale_genre:
        return locale_genre

    # Substring match: map key contained in raw tag (avoid ultra-short keys like "pop")
    for key, genre in AUDIODB_GENRE_MAP.items():
        if len(key) < _SUBSTRING_MIN_LEN:
            continue
        if key in tag:
            return genre

    return None


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

            for tag in _parse_genres_list(row.get("genres")):
                genre = map_raw_genre(tag)
                if genre:
                    lookup[norm_name] = genre
                    break
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

            # Try raw sub-genres first
            genre = None
            for tag in _parse_genres_list(row.get("genres")):
                genre = map_raw_genre(tag)
                if genre:
                    break

            # Fall back to main_genre
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
