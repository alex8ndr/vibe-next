from __future__ import annotations

import polars as pl

from genre_mapping import load_artist_genre_lookup
from language_config import (
    GENRE_LANG_OVERRIDES,
    TAG_FASTTEXT_THRESHOLD,
    FALLBACK_FASTTEXT_THRESHOLD,
)
from language_detection import load_fasttext_model, clean_track_title, detect_language
from track_dedup import normalize_artist_name


def resolve_artist_languages(
    df: pl.DataFrame,
    verbose: bool,
    max_titles: int = 30,
    tag_fasttext_threshold: float = TAG_FASTTEXT_THRESHOLD,
    fallback_fasttext_threshold: float = FALLBACK_FASTTEXT_THRESHOLD,
) -> dict[str, str]:
    """Resolve one final language code per artist.

    Cascade:
      1) genre override (always wins)
      2) tag_lang exists -> FastText if conf>=threshold else tag_lang
      3) no tag_lang/override -> default en, FastText can override at high conf
    """
    if "artist_name" not in df.columns or "track_name" not in df.columns:
        raise ValueError("resolve_artist_languages requires artist_name and track_name columns")
    if "genre" not in df.columns:
        raise ValueError("resolve_artist_languages requires genre column")

    if verbose:
        print("Loading artist tag language lookup...")
    _, tag_lang_lookup = load_artist_genre_lookup()

    artist_rows = (
        df.group_by("artist_name")
        .agg([
            pl.col("track_name").sort_by("popularity", descending=True).head(max_titles).alias("_top_titles"),
            pl.col("genre").drop_nulls().first().alias("_genre"),
        ])
    )

    if verbose:
        print(f"Resolving languages for {artist_rows.height:,} artists...")
    model = load_fasttext_model()

    artist_lang: dict[str, str] = {}
    override_count = 0
    tag_count = 0
    fallback_count = 0

    for row in artist_rows.iter_rows(named=True):
        artist_name = row["artist_name"]
        genre = row.get("_genre")
        top_titles = row.get("_top_titles") or []

        if not artist_name or not isinstance(artist_name, str):
            continue

        override_lang = GENRE_LANG_OVERRIDES.get(genre) if isinstance(genre, str) else None
        if override_lang:
            artist_lang[artist_name] = override_lang
            override_count += 1
            continue

        norm_name = normalize_artist_name(artist_name)
        tag_lang = tag_lang_lookup.get(norm_name)

        cleaned_titles: list[str] = []
        for title in top_titles:
            if isinstance(title, str):
                cleaned = clean_track_title(title)
                if cleaned:
                    cleaned_titles.append(cleaned)

        combined = " | ".join(cleaned_titles)
        detected_lang = None
        detected_conf = 0.0
        if combined:
            detected_lang, detected_conf = detect_language(model, combined)

        if tag_lang:
            if detected_lang and detected_conf >= tag_fasttext_threshold:
                artist_lang[artist_name] = detected_lang
            else:
                artist_lang[artist_name] = tag_lang
            tag_count += 1
            continue

        if detected_lang and detected_conf >= fallback_fasttext_threshold:
            artist_lang[artist_name] = detected_lang
        else:
            artist_lang[artist_name] = "en"
        fallback_count += 1

    if verbose:
        print(
            "Language resolution stats: "
            f"genre-override={override_count:,}, "
            f"tag-lang={tag_count:,}, "
            f"default/fallback={fallback_count:,}"
        )

    return artist_lang
