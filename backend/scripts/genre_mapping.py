"""
Map external genre tags to the internal Vibe genre vocabulary.

Used by filter-time artist genre enrichment.
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

# Valid output genre names
_VALID_GENRES = set(GENRE_DEFINITIONS.keys())


# Sentinel: locale detected but no supported locale output genre
_BLOCK = object()

# Explicit locale phrase overrides. `None` means block.
_LOCALE_OVERRIDES = {
    # French
    "french hip hop": "french-hip-hop",
    "french rap": "french-hip-hop",
    "rap francais": "french-hip-hop",
    "rap français": "french-hip-hop",
    "pop urbaine": "french-hip-hop",
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
    "cantonese traditional": "cantopop",
    "taiwanese indigenous": "world",
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

# Locale keywords that map directly to supported output genres.
_LOCALE_KEYWORDS = {
    # European with dedicated genres
    "french": "french",
    "francais": "french",
    "français": "french",
    "francaise": "french",
    "française": "french",
    "german": "german",
    "spanish": "spanish",
    "swedish": "swedish",
    # Asian
    "chinese": "cantopop",
    "taiwanese": "cantopop",
    "taiwan": "cantopop",
    "mandarin": "cantopop",
    "cantonese": "cantopop",
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
    "hindi": "indian",
    "malayalam": "indian",
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

# Locale keywords to block when no dedicated output genre exists.
_NON_ENGLISH_PREFIXES = frozenset({
    # Europe (non-English speaking, no dedicated genre)
    "dutch", "belgian", "flemish",
    "italian", "portuguese", "greek", "icelandic",
    "italiano", "italiana",
    "norwegian", "danish", "finnish", "estonian", "latvian", "lithuanian",
    "czech", "slovak", "hungarian", "polish", "romanian",
    "serbian", "croatian", "bosnian", "slovenian", "bulgarian", "yugoslav",
    "ukrainian", "belarusian", "russian",
    "turkish", "georgian", "armenian",
    # Asia (without dedicated genres)
    "indonesian", "thai", "vietnamese", "filipino", "pinoy",
    "malaysian", "malay", "singaporean",
    # Middle East
    "persian", "arab", "arabic", "lebanese", "palestinian", "syrian",
    "arabesk",
    "israeli", "egyptian", "moroccan",
})

# Guard for positive locale routing. Example: "french cinema" should not map to `french`.
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
    "samba", "salsa", "swing", "soundtrack", "film", "chanson", "variete",
)

# Pre-compiled locale regexes
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

# Safe prefixes to strip before exact mapping; longest first.
_SAFE_PREFIXES: tuple[str, ...] = tuple(sorted([
    # English-speaking nationalities
    "australian", "canadian", "british", "american", "uk",
    "scottish", "irish", "welsh", "new zealand",
    # Era / style modifiers
    "modern", "classic", "contemporary", "old school", "old-school",
    "neo", "nu", "new",
    # Intensity / texture modifiers (safe to strip for genre routing)
    "deep", "dark", "melodic", "atmospheric", "raw",
    "technical", "symphonic", "brutal", "epic",
], key=len, reverse=True))

# Last-resort substring rules for unambiguous multi-word compounds.
# Single-word substring rules are intentionally excluded to avoid false matches.
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
    }.items()
]


def _map_locale_genre(tag: str):
    """Resolve locale-specific tags.

    Returns:
        genre string  -> dedicated locale genre
        _BLOCK        -> locale should be excluded
        None          -> continue standard mapping
    """
    for key, genre in _LOCALE_OVERRIDES.items():
        if key in tag:
            return genre if genre is not None else _BLOCK

    # Positive locale routing requires a genre token guard.
    if _GENERIC_TOKEN_RE.search(tag):
        for locale, genre in _LOCALE_KEYWORDS.items():
            if _LOCALE_KEYWORD_RES[locale].search(tag):
                return genre

    # Block unsupported locales
    if _NON_ENGLISH_RE.search(tag):
        return _BLOCK

    return None


# Locale genres that remain allowed after locale blocking logic
_LOCALE_OUTPUT_GENRES = (
    set(_LOCALE_KEYWORDS.values())
    | {v for v in _LOCALE_OVERRIDES.values() if v is not None}
)


def _map_standard_genre(tag: str) -> str | None:
    """Map using exact match, direct map, safe-prefix strip, then compound fallback."""
    if tag in _VALID_GENRES:
        return tag
    if tag in AUDIODB_GENRE_MAP:
        return AUDIODB_GENRE_MAP[tag]
    # Safe-prefix strip, then retry exact/direct lookup
    for prefix in _SAFE_PREFIXES:
        if tag.startswith(prefix + " "):
            remainder = tag[len(prefix) + 1:]
            if remainder in _VALID_GENRES:
                return remainder
            if remainder in AUDIODB_GENRE_MAP:
                return AUDIODB_GENRE_MAP[remainder]
    # Multi-word compound fallback
    for pattern, genre in _COMPOUND_SUBSTRING_RULES:
        if pattern.search(tag):
            return genre
    return None


def explain_raw_genre(raw_genre: str) -> dict[str, str | None]:
    """Return a trace for how one raw genre tag was resolved."""
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

    # Prefix-strip trace
    for prefix in _SAFE_PREFIXES:
        if tag.startswith(prefix + " "):
            remainder = tag[len(prefix) + 1:]
            if remainder in _VALID_GENRES:
                return {"tag": tag, "mapped_genre": remainder, "reason": f"prefix-strip:{prefix}->exact-valid"}
            if remainder in AUDIODB_GENRE_MAP:
                return {"tag": tag, "mapped_genre": AUDIODB_GENRE_MAP[remainder], "reason": f"prefix-strip:{prefix}->exact-map"}

    # Compound fallback trace
    for pattern, genre in _COMPOUND_SUBSTRING_RULES:
        if pattern.search(tag):
            return {"tag": tag, "mapped_genre": genre, "reason": f"compound:{pattern.pattern}"}

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


def map_artist_tags(tags: list[str], *, _return_locale_flag: bool = False):
    """Map a list of artist tags to a single genre.

    Locale-routed genres win when there is a strong locale signal
    (>= 2 locale tags or no standard alternatives).  A single locale
    tag among many standard tags is treated as noise (e.g. Phoenix
    having one French tag at the end of an otherwise English tag list).

    Returns:
        When _return_locale_flag is False (default):
            genre string  -> matched genre
            _BLOCK        -> all tags blocked, no locale output fallback
            None          -> no match
        When _return_locale_flag is True:
            (genre_or_BLOCK_or_None, is_locale: bool)
    """
    blocked = False
    first_standard = None
    first_locale = None
    locale_count = 0
    standard_count = 0
    first_mapped_is_locale = None  # True/False once first mappable tag is seen

    for raw_tag in tags:
        tag = raw_tag.lower().strip()
        if not tag:
            continue

        locale_result = _map_locale_genre(tag)
        if locale_result is _BLOCK:
            blocked = True
            continue
        if locale_result is not None:
            locale_count += 1
            if first_locale is None:
                first_locale = locale_result
            if first_mapped_is_locale is None:
                first_mapped_is_locale = True
            continue

        if first_standard is None or standard_count < locale_count + 5:
            genre = _map_standard_genre(tag)
            if genre:
                if not (blocked and genre not in _LOCALE_OUTPUT_GENRES):
                    standard_count += 1
                    if first_standard is None:
                        first_standard = genre
                    if first_mapped_is_locale is None:
                        first_mapped_is_locale = False

    # Locale wins with strong signal (>= 2 tags), no standard alternative,
    # or when the very first mappable tag was locale (position signal).
    if first_locale is not None and (
        locale_count >= 2 or standard_count == 0 or first_mapped_is_locale
    ):
        result, is_locale = first_locale, True
    elif first_standard is not None:
        result, is_locale = first_standard, False
    elif first_locale is not None:
        result, is_locale = first_locale, True
    else:
        result, is_locale = (_BLOCK if blocked else None), False

    if _return_locale_flag:
        return result, is_locale
    return result


def explain_artist_tags(tags: list[str]) -> dict[str, object]:
    """Return a structured explanation of artist-level tag mapping."""
    blocked = False
    first_standard = None
    first_locale = None
    locale_count = 0
    standard_count = 0
    first_mapped_is_locale = None
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
            locale_count += 1
            if first_locale is None:
                first_locale = locale_result
            if first_mapped_is_locale is None:
                first_mapped_is_locale = True
            details.append({"tag": tag, "status": "locale-route", "mapped": locale_result})
            continue

        mapped = _map_standard_genre(tag)
        if mapped:
            if blocked and mapped not in _LOCALE_OUTPUT_GENRES:
                details.append({"tag": tag, "status": "blocked-after-locale", "mapped": mapped})
                continue
            standard_count += 1
            if first_standard is None:
                first_standard = mapped
                details.append({"tag": tag, "status": "first-match", "mapped": mapped})
            else:
                details.append({"tag": tag, "status": "later-match", "mapped": mapped})
            if first_mapped_is_locale is None:
                first_mapped_is_locale = False
        else:
            details.append({"tag": tag, "status": "no-match", "mapped": None})

    # Count genre votes across all mapped tags (including locale)
    votes: dict[str, int] = {}
    for d in details:
        m = d.get("mapped")
        if m and d["status"] not in ("blocked-locale", "blocked-after-locale"):
            votes[m] = votes.get(m, 0) + 1

    # Determine result using same voting logic as map_artist_tags
    if first_locale is not None and (
        locale_count >= 2 or standard_count == 0 or first_mapped_is_locale
    ):
        result = first_locale
    elif first_standard is not None:
        result = first_standard
    elif first_locale is not None:
        result = first_locale
    else:
        result = _BLOCK if blocked else None

    return {"result": result, "blocked": blocked, "details": details, "votes": votes}


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

    Blocking is tracked per Spotify artist_id to prevent different artists
    with the same normalized name from cross-contaminating each other.
    """
    # Source quality: lower is better (used as tiebreaker after popularity).
    _source_quality = {YAMAC_GENRE: 0, VECTORQL_GENRE: 1, SERKAN_GENRE: 2}

    # Collect candidates per normalized artist from all sources.
    # Value shape: list[(genre, popularity, artist_id, source_quality, is_locale)]
    candidates: dict[str, list[tuple[str, int, str, int, bool]]] = {}
    blocked_ids: set[str] = set()
    blocked_pops: dict[str, int] = {}  # norm_name -> max blocked popularity
    seen_ids_by_name: dict[str, set[str]] = {}

    # Cache tag-tuple mapping results (high reuse across rows)
    _tag_cache: dict[tuple, tuple] = {}

    for path in [SERKAN_GENRE, YAMAC_GENRE, VECTORQL_GENRE]:
        if not path.exists():
            print(f"Genre source not found: {path}")
            continue

        src_q = _source_quality.get(path, 2)
        df = pl.read_parquet(path)

        # Extract columns as lists (avoids iter_rows dict creation overhead)
        names = df["name"].to_list()
        ids = df["id"].to_list() if "id" in df.columns else [None] * len(df)
        genres_lists = df["genres"].to_list()
        pops = df["popularity"].to_list() if "popularity" in df.columns else [0] * len(df)
        fallbacks = df["fallback"].to_list() if "fallback" in df.columns else [None] * len(df)

        for name, artist_id, tags, pop, fallback in zip(names, ids, genres_lists, pops, fallbacks):
            if not name:
                continue
            norm_name = normalize_artist_name(str(name))
            artist_id = artist_id or ""
            if artist_id:
                seen_ids_by_name.setdefault(norm_name, set()).add(artist_id)

            if not tags:
                tags = []
            pop = pop or 0

            # Cached tag mapping (returns (genre, is_locale) tuples)
            tags_key = tuple(tags) if isinstance(tags, list) else (tags,)
            if tags_key in _tag_cache:
                genre, is_locale = _tag_cache[tags_key]
            else:
                genre, is_locale = map_artist_tags(tags, _return_locale_flag=True)
                _tag_cache[tags_key] = (genre, is_locale)

            # Fallback to source main genre (except blocked)
            if genre is _BLOCK:
                if artist_id:
                    blocked_ids.add(artist_id)
                blocked_pops[norm_name] = max(blocked_pops.get(norm_name, 0), int(pop or 0))
                continue
            if not genre:
                if fallback and isinstance(fallback, str):
                    genre = _map_standard_genre(fallback.strip().lower())
                    is_locale = False

            if not genre:
                continue

            candidates.setdefault(norm_name, []).append(
                (genre, int(pop or 0), artist_id, src_q, is_locale)
            )

    lookup: dict[str, str] = {}
    blocked_artists: set[str] = set()
    for norm_name, rows in candidates.items():
        # Prefer non-blocked IDs when names collide
        non_blocked = [(g, p, aid, sq, loc) for g, p, aid, sq, loc in rows
                       if aid not in blocked_ids]
        from_blocked = [(g, p, aid, sq, loc) for g, p, aid, sq, loc in rows
                        if aid in blocked_ids]

        if non_blocked:
            max_non_blocked_pop = max(p for _, p, *_ in non_blocked)
            max_blocked_pop = blocked_pops.get(norm_name, 0)
            # If a blocked entry is much more popular, the non-blocked entries
            # are likely false matches from different artists with the same name
            if max_blocked_pop > 0 and max_non_blocked_pop < max_blocked_pop * 0.25:
                blocked_artists.add(norm_name)
                continue

            # Detect name collisions: multiple distinct Spotify artist IDs
            distinct_ids = {aid for _, _, aid, _, _ in non_blocked if aid}
            name_collision = len(distinct_ids) > 1

            if name_collision:
                # Different artists with same name — popularity wins,
                # source quality as tiebreaker, no locale priority
                non_blocked.sort(key=lambda item: (
                    -item[1],   # -popularity
                    item[3],    # source_quality (lower = better)
                    item[0],    # genre_name
                ))
            else:
                # Same artist — locale-routed entries get priority as tiebreaker
                non_blocked.sort(key=lambda item: (
                    0 if item[4] else 1,  # is_locale flag
                    -item[1],             # -popularity
                    item[3],              # source_quality
                    item[0],              # genre_name
                ))
            lookup[norm_name] = non_blocked[0][0]
        elif from_blocked:
            blocked_artists.add(norm_name)
            locale_only = [r for r in from_blocked if r[4]]  # is_locale flag
            if locale_only:
                locale_only.sort(key=lambda item: (-item[1], item[3], item[0]))
                lookup[norm_name] = locale_only[0][0]

    # Names with only blocked IDs may never enter candidates; still mark blocked.
    for norm_name, ids in seen_ids_by_name.items():
        if ids and ids.issubset(blocked_ids) and norm_name not in lookup:
            blocked_artists.add(norm_name)

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

    # In override mode, null blocked artists unless locked or locale-genre allowed.
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
