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

from collections import Counter
import re
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from genre_families import GENRE_DEFINITIONS
from genre_locale_config import (
    LOCALE_TO_LANG as _LOCALE_TO_LANG,
    LOCALE_PHRASE_RULES as _LOCALE_PHRASE_RULES,
    LOCALE_CONNECTOR_TOKENS as _LOCALE_CONNECTOR_TOKENS,
    LOCALE_SCENE_REMAPS as _LOCALE_SCENE_REMAPS,
)
from paths import SERKAN_GENRE, YAMAC_GENRE, VECTORQL_GENRE
from track_dedup import normalize_artist_name
from utils import AUDIODB_GENRE_MAP

# Valid output genre names
_VALID_GENRES = set(GENRE_DEFINITIONS.keys())


_CANONICAL_SEP_RE = re.compile(r"[-_/\\\s]+")


def _canonicalize_tag_for_lookup(tag: str) -> str:
    return _CANONICAL_SEP_RE.sub(" ", tag.strip().lower())


def _canonicalize_tag_compact(tag: str) -> str:
    return _CANONICAL_SEP_RE.sub("", tag.strip().lower())


def _build_canonical_map(source: dict[str, str]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for key, mapped in source.items():
        canon = _canonicalize_tag_for_lookup(key)
        candidates.setdefault(canon, set()).add(mapped)
    return {canon: next(iter(values)) for canon, values in candidates.items() if len(values) == 1}


def _build_compact_canonical_map(source: dict[str, str]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for key, mapped in source.items():
        canon = _canonicalize_tag_compact(key)
        candidates.setdefault(canon, set()).add(mapped)
    return {canon: next(iter(values)) for canon, values in candidates.items() if len(values) == 1}


_CANONICAL_AUDIODB_MAP = _build_canonical_map(AUDIODB_GENRE_MAP)
_CANONICAL_VALID_GENRE_MAP = _build_canonical_map({genre: genre for genre in _VALID_GENRES})
_COMPACT_CANONICAL_AUDIODB_MAP = _build_compact_canonical_map(AUDIODB_GENRE_MAP)
_COMPACT_CANONICAL_VALID_GENRE_MAP = _build_compact_canonical_map({genre: genre for genre in _VALID_GENRES})


# ---------------------------------------------------------------------------
# Locale → ISO language code mapping (merged from old _LOCALE_KEYWORDS +
# _NON_ENGLISH_PREFIXES).  Value is an ISO 639-1 code, or None when the
# locale is ambiguous (multi-lingual country).
# ---------------------------------------------------------------------------
# Pre-compiled regexes
_LOCALE_ALL_RE = re.compile(
    r"\b(?:" + "|".join(
        re.escape(p) for p in sorted(_LOCALE_TO_LANG, key=len, reverse=True)
    ) + r")\b"
)

_CONNECTOR_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(token) for token in _LOCALE_CONNECTOR_TOKENS) + r")\b"
)

_LOCALE_PHRASE_RULE_RES: tuple[tuple[re.Pattern, tuple[str | None, str | None]], ...] = tuple(
    (
        re.compile(rf"\b{re.escape(phrase)}\b"),
        (genre, lang),
    )
    for phrase, (genre, lang) in sorted(_LOCALE_PHRASE_RULES.items(), key=lambda item: len(item[0]), reverse=True)
)

_US_CA_LOCATION_PREFIXES: tuple[str, ...] = (
    # United States (state/city labels commonly present in tags)
    "new york", "nyc", "brooklyn", "queens", "bronx", "harlem",
    "los angeles", "la", "california", "cali", "bay area", "san francisco",
    "chicago", "detroit", "atlanta", "miami", "florida", "houston",
    "texas", "memphis", "nashville", "seattle", "portland", "oakland",
    "philadelphia", "philly", "new orleans", "louisiana", "boston",
    "washington", "dc", "new jersey", "jersey", "ohio",

    # Canada (province/city labels commonly present in tags)
    "toronto", "montreal", "vancouver", "ottawa", "calgary", "edmonton",
    "quebec", "quebecois", "ontario", "alberta", "british columbia",
    "manitoba", "saskatchewan", "nova scotia", "newfoundland",
    "canada", "canadian",
)

# Safe prefixes to strip before exact mapping; longest first.
_SAFE_PREFIXES: tuple[str, ...] = tuple(sorted([
    "australian", "canadian", "british", "american", "uk", "english",
    "scottish", "irish", "welsh", "new zealand", "nz", "aussie", "aus",
    "modern", "classic", "contemporary", "old school", "old-school",
    "neo", "nu", "new",
    "deep", "dark", "melodic", "atmospheric", "raw",
    "technical", "symphonic", "brutal", "epic",
    *_US_CA_LOCATION_PREFIXES,
], key=len, reverse=True))


def _map_locale_tag(tag: str) -> tuple[str | None, str | None]:
    """Resolve locale-specific tags.

    Returns:
        (genre, tag_lang) — genre and/or language signal from this tag.
        (None, None) if tag has no locale content.
    """
    for phrase_re, (genre, lang) in _LOCALE_PHRASE_RULE_RES:
        if phrase_re.search(tag):
            return genre, lang

    m = _LOCALE_ALL_RE.search(tag)
    if not m:
        return None, None

    locale_word = m.group(0)
    lang = _LOCALE_TO_LANG.get(locale_word)

    remainder = _strip_locale_from_tag(tag, locale_word)
    remainder_genre = _map_remainder_genre(remainder)
    if remainder_genre is not None:
        mapped_genre = _remap_locale_scene_genre(locale_word, remainder_genre)
        return mapped_genre, lang

    return None, lang


def _strip_locale_from_tag(tag: str, locale_word: str) -> str:
    remainder = tag.replace(locale_word, " ")
    remainder = _CONNECTOR_TOKEN_RE.sub(" ", remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip()
    return remainder


def _map_remainder_genre(remainder: str) -> str | None:
    if not remainder:
        return None

    direct = _map_standard_genre(remainder)
    if direct is not None:
        return direct

    tokens = remainder.split()
    if not tokens:
        return None

    best_genre: str | None = None
    best_score: tuple[int, int] | None = None
    max_ngram = min(4, len(tokens))

    for n in range(max_ngram, 0, -1):
        for start_idx in range(0, len(tokens) - n + 1):
            phrase = " ".join(tokens[start_idx:start_idx + n])
            mapped = _map_standard_genre(phrase)
            if mapped is None:
                continue

            score = (n, -start_idx)
            if best_genre is None or (best_score is not None and score > best_score):
                best_genre = mapped
                best_score = score

    return best_genre


def _remap_locale_scene_genre(locale_word: str, mapped_genre: str) -> str:
    scene_map = _LOCALE_SCENE_REMAPS.get(locale_word)
    if not scene_map:
        return mapped_genre
    return scene_map.get(mapped_genre, mapped_genre)


def _map_standard_genre_with_reason(tag: str) -> tuple[str | None, str]:
    if tag in _VALID_GENRES:
        return tag, "exact-valid"

    mapped = AUDIODB_GENRE_MAP.get(tag)
    if mapped is not None:
        return mapped, "exact-map"

    canonical = _canonicalize_tag_for_lookup(tag)
    mapped_valid_canonical = _CANONICAL_VALID_GENRE_MAP.get(canonical)
    if mapped_valid_canonical is not None:
        return mapped_valid_canonical, "canonical-valid"

    mapped_canonical = _CANONICAL_AUDIODB_MAP.get(canonical)
    if mapped_canonical is not None:
        return mapped_canonical, "canonical-map"

    compact = _canonicalize_tag_compact(tag)
    mapped_valid_compact = _COMPACT_CANONICAL_VALID_GENRE_MAP.get(compact)
    if mapped_valid_compact is not None:
        return mapped_valid_compact, "compact-canonical-valid"

    mapped_compact = _COMPACT_CANONICAL_AUDIODB_MAP.get(compact)
    if mapped_compact is not None:
        return mapped_compact, "compact-canonical-map"

    for prefix in _SAFE_PREFIXES:
        if not tag.startswith(prefix + " "):
            continue

        remainder = tag[len(prefix) + 1:]
        if remainder in _VALID_GENRES:
            return remainder, f"prefix-strip:{prefix}->exact-valid"

        mapped_remainder = AUDIODB_GENRE_MAP.get(remainder)
        if mapped_remainder is not None:
            return mapped_remainder, f"prefix-strip:{prefix}->exact-map"

    return None, "none"


def _map_standard_genre(tag: str) -> str | None:
    """Map using exact match, direct map, then safe-prefix strip."""
    mapped, _reason = _map_standard_genre_with_reason(tag)
    return mapped


def explain_raw_genre(raw_genre: str) -> dict[str, object]:
    """Return a trace for how one raw genre tag was resolved."""
    tag = (raw_genre or "").lower().strip()
    if not tag:
        return {"tag": tag, "mapped_genre": None, "tag_lang": None, "reason": "none"}

    mapped, reason = _map_standard_genre_with_reason(tag)
    if reason == "exact-valid":
        return {"tag": tag, "mapped_genre": mapped, "tag_lang": None, "reason": reason}

    genre, lang = _map_locale_tag(tag)
    if genre is not None:
        return {"tag": tag, "mapped_genre": genre, "tag_lang": lang, "reason": "locale-route"}
    if lang is not None:
        if mapped is not None:
            return {
                "tag": tag,
                "mapped_genre": mapped,
                "tag_lang": lang,
                "reason": f"{reason}+locale-lang",
            }
        return {"tag": tag, "mapped_genre": None, "tag_lang": lang, "reason": "locale-lang-only"}

    if mapped is not None:
        return {"tag": tag, "mapped_genre": mapped, "tag_lang": None, "reason": reason}

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
    genre, tag_lang, _has_locale_signal = map_artist_tags_with_lang_signal(tags)
    return genre, tag_lang


def map_artist_tags_with_lang_signal(tags: list[str]) -> tuple[str | None, str | None, bool]:
    """Map artist tags and preserve whether locale context was present.

    Returns:
        (genre, tag_lang, has_locale_signal)
        - genre: selected internal genre or None
        - tag_lang: resolved language hint (may be None)
        - has_locale_signal: True when any locale-routed tag was present,
          even if locale language is ambiguous (e.g. ``swiss``, ``belgian``).
    """
    first_standard: str | None = None
    first_locale_genre: str | None = None
    locale_count = 0
    standard_count = 0
    first_mapped_is_locale: bool | None = None
    all_langs: list[str] = []
    has_locale_signal = False

    for raw_tag in tags:
        tag = (raw_tag or "").lower().strip()
        if not tag:
            continue

        locale_genre, locale_lang = _map_locale_tag(tag)
        if locale_lang is not None:
            all_langs.append(locale_lang)

        if locale_genre is not None or locale_lang is not None:
            has_locale_signal = True

        if locale_genre is not None:
            locale_count += 1
            if first_locale_genre is None:
                first_locale_genre = locale_genre
            if first_mapped_is_locale is None:
                first_mapped_is_locale = True
            continue

        mapped_genre = _map_standard_genre(tag)
        if mapped_genre is not None:
            standard_count += 1
            if first_standard is None:
                first_standard = mapped_genre
            if first_mapped_is_locale is None:
                first_mapped_is_locale = False

    if locale_count == 1 and first_mapped_is_locale is False:
        has_locale_signal = False

    return (
        _choose_artist_genre(
            first_standard,
            first_locale_genre,
            locale_count,
            standard_count,
            first_mapped_is_locale,
        ),
        _select_tag_lang(
            all_langs,
            locale_count,
            first_mapped_is_locale,
        ),
        has_locale_signal,
    )


def explain_artist_tags(tags: list[str]) -> dict[str, object]:
    """Return a structured explanation of artist-level tag mapping."""
    result, tag_lang_selected, _has_locale_signal = map_artist_tags_with_lang_signal(tags)
    analysis = _analyze_artist_tags(tags, include_details=True)
    return {
        "result": result,
        "tag_lang": tag_lang_selected,
        "details": analysis["details"],
        "votes": analysis["votes"],
    }


def _choose_artist_genre(
    first_standard: str | None,
    first_locale_genre: str | None,
    locale_count: int,
    standard_count: int,
    first_mapped_is_locale: bool | None,
) -> str | None:
    if first_locale_genre is not None and (
        locale_count >= 2 or standard_count == 0 or first_mapped_is_locale
    ):
        return first_locale_genre
    if first_standard is not None:
        return first_standard
    return first_locale_genre


def _select_tag_lang(
    all_langs: list[str],
    locale_count: int,
    first_mapped_is_locale: bool | None,
) -> str | None:
    if not all_langs:
        return None

    lang_counts = Counter(all_langs)
    if not lang_counts:
        return None

    top_lang, top_count = lang_counts.most_common(1)[0]

    # Avoid overfitting to a single trailing locale tag when primary tag routing
    # was standard (e.g. "... , french ..." noise on otherwise non-french artists).
    if top_count == 1 and locale_count == 1 and first_mapped_is_locale is False:
        return None

    return top_lang


def _analyze_artist_tags(tags: list[str], *, include_details: bool) -> dict[str, object]:
    first_standard: str | None = None
    first_locale_genre: str | None = None
    locale_count = 0
    standard_count = 0
    first_mapped_is_locale: bool | None = None
    all_langs: list[str] = []
    details: list[dict[str, object]] = []
    votes: dict[str, int] = {} if include_details else {}

    for raw_tag in tags:
        tag = (raw_tag or "").lower().strip()
        if not tag:
            continue

        locale_genre, locale_lang = _map_locale_tag(tag)
        if locale_lang is not None:
            all_langs.append(locale_lang)

        if locale_genre is not None:
            locale_count += 1
            if first_locale_genre is None:
                first_locale_genre = locale_genre
            if first_mapped_is_locale is None:
                first_mapped_is_locale = True
            if include_details:
                votes[locale_genre] = votes.get(locale_genre, 0) + 1
                details.append(
                    {
                        "tag": tag,
                        "status": "locale-route",
                        "mapped": locale_genre,
                        "tag_lang": locale_lang,
                    }
                )
            continue

        mapped_genre, _reason = _map_standard_genre_with_reason(tag)
        if mapped_genre is not None:
            standard_count += 1
            is_first_standard = first_standard is None
            if first_standard is None:
                first_standard = mapped_genre
            if first_mapped_is_locale is None:
                first_mapped_is_locale = False
            if include_details:
                votes[mapped_genre] = votes.get(mapped_genre, 0) + 1
                details.append(
                    {
                        "tag": tag,
                        "status": "first-match" if is_first_standard else "later-match",
                        "mapped": mapped_genre,
                        "tag_lang": locale_lang,
                    }
                )
            continue

        if include_details:
            if locale_lang is not None:
                details.append(
                    {
                        "tag": tag,
                        "status": "locale-lang-only",
                        "mapped": None,
                        "tag_lang": locale_lang,
                    }
                )
            else:
                details.append(
                    {
                        "tag": tag,
                        "status": "no-match",
                        "mapped": None,
                        "tag_lang": None,
                    }
                )

    return {
        "result": _choose_artist_genre(
            first_standard,
            first_locale_genre,
            locale_count,
            standard_count,
            first_mapped_is_locale,
        ),
        "tag_lang": _select_tag_lang(
            all_langs,
            locale_count,
            first_mapped_is_locale,
        ),
        "details": details,
        "votes": votes,
    }


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


def load_artist_genre_lookup(
    *,
    include_lang_signal: bool = False,
) -> tuple[dict[str, str], dict[str, str]] | tuple[dict[str, str], dict[str, str], dict[str, bool]]:
    """
    Load preprocessed artist genre parquets and build lookups.

    Returns:
        Default:
            (genre_lookup, lang_lookup)
        When include_lang_signal=True:
            (genre_lookup, lang_lookup, lang_signal_lookup)

        All dicts are keyed by normalized artist name.
        - genre_lookup maps to genre string.
        - lang_lookup maps to ISO tag language code.
        - lang_signal_lookup is True when locale signal exists, even if
          language code is ambiguous (e.g. belgian/swiss).

    Sources are checked sequentially in quality order (Yamac → Vectorql → Serkan).
    """
    _tag_cache: dict[tuple, tuple[str | None, str | None, bool]] = {}
    genre_lookup: dict[str, str] = {}
    lang_lookup: dict[str, str] = {}
    lang_signal_lookup: dict[str, bool] = {}

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
                genre, tag_lang, has_locale_signal = _tag_cache[tags_key]
            else:
                genre, tag_lang, has_locale_signal = map_artist_tags_with_lang_signal(tags)
                _tag_cache[tags_key] = (genre, tag_lang, has_locale_signal)

            if not genre and fallback and isinstance(fallback, str):
                genre = _map_standard_genre(fallback.strip().lower())

            if genre:
                genre_lookup[norm_name] = genre
            if tag_lang:
                lang_lookup[norm_name] = tag_lang
            if has_locale_signal or tag_lang is not None:
                lang_signal_lookup[norm_name] = True

    if include_lang_signal:
        return genre_lookup, lang_lookup, lang_signal_lookup
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
