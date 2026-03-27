from __future__ import annotations

from collections import Counter

import polars as pl

from genre_mapping import load_artist_genre_lookup
from language_config import (
    GENRE_LANG_OVERRIDES,
    LANGUAGE_MAX_TITLES,
    TAG_FASTTEXT_THRESHOLD,
    LOCALE_SIGNAL_FASTTEXT_THRESHOLD,
    FALLBACK_FASTTEXT_THRESHOLD,
    PROTECTED_TAG_LANG_CODES,
    VOTE_FALLBACK_CONF_FLOOR,
    VOTE_FALLBACK_MIN_VOTES,
    VOTE_FALLBACK_DOMINANCE,
)
from language_detection import load_fasttext_model, clean_track_title, detect_language
from track_dedup import normalize_artist_name


def _vote_language_from_titles(
    model,
    cleaned_titles: list[str],
    *,
    conf_floor: float,
    min_votes: int,
    dominance: float,
) -> str | None:
    votes: Counter[str] = Counter()

    for text in cleaned_titles:
        lang, conf = detect_language(model, text)
        if not lang:
            continue
        if conf < conf_floor:
            continue
        votes[lang] += 1

    if not votes:
        return None

    top_lang, top_count = votes.most_common(1)[0]
    total_votes = sum(votes.values())
    if top_count < min_votes:
        return None
    if total_votes <= 0:
        return None
    if (top_count / total_votes) < dominance:
        return None
    return top_lang


def resolve_artist_languages(
    df: pl.DataFrame,
    verbose: bool,
    max_titles: int = LANGUAGE_MAX_TITLES,
    tag_fasttext_threshold: float = TAG_FASTTEXT_THRESHOLD,
    locale_signal_fasttext_threshold: float = LOCALE_SIGNAL_FASTTEXT_THRESHOLD,
    fallback_fasttext_threshold: float = FALLBACK_FASTTEXT_THRESHOLD,
    vote_fallback_conf_floor: float = VOTE_FALLBACK_CONF_FLOOR,
    vote_fallback_min_votes: int = VOTE_FALLBACK_MIN_VOTES,
    vote_fallback_dominance: float = VOTE_FALLBACK_DOMINANCE,
    protected_tag_lang_codes: frozenset[str] = PROTECTED_TAG_LANG_CODES,
) -> dict[str, str]:
    """Resolve one final language code per artist.

        Cascade:
            1) genre override (always wins)
              2) explicit tag_lang exists ->
                  FastText if conf>=TAG threshold, else keep tag_lang
              3) locale signal exists but no tag_lang ->
                  FastText if conf>=LOCALE threshold, else en
              4) no tag signal/override -> default en, FastText can override at fallback threshold
    """
    if "artist_name" not in df.columns or "track_name" not in df.columns:
        raise ValueError("resolve_artist_languages requires artist_name and track_name columns")
    if "genre" not in df.columns:
        raise ValueError("resolve_artist_languages requires genre column")

    if verbose:
        print("Loading artist tag language lookup...")
    _, tag_lang_lookup, tag_signal_lookup = load_artist_genre_lookup(include_lang_signal=True)

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
    explicit_tag_count = 0
    locale_signal_count = 0
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
        tag_lang_norm = tag_lang.strip().lower() if isinstance(tag_lang, str) else None
        tag_lang_base = tag_lang_norm.split("-", 1)[0] if tag_lang_norm else None

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

        has_tag_signal = bool(tag_lang_norm) or bool(tag_signal_lookup.get(norm_name))

        if tag_lang_norm:
            # Accept both full locale tags (e.g. hi-IN) and base ISO tags.
            is_protected_tag_lang = (
                tag_lang_norm in protected_tag_lang_codes
                or (tag_lang_base is not None and tag_lang_base in protected_tag_lang_codes)
            )
            if is_protected_tag_lang:
                artist_lang[artist_name] = tag_lang_base or tag_lang_norm
            elif detected_lang and detected_conf >= tag_fasttext_threshold:
                artist_lang[artist_name] = detected_lang
            else:
                artist_lang[artist_name] = tag_lang_base or tag_lang_norm
            explicit_tag_count += 1
            continue

        if has_tag_signal:
            if detected_lang and detected_conf >= locale_signal_fasttext_threshold:
                artist_lang[artist_name] = detected_lang
            else:
                voted_lang = _vote_language_from_titles(
                    model,
                    cleaned_titles,
                    conf_floor=vote_fallback_conf_floor,
                    min_votes=vote_fallback_min_votes,
                    dominance=vote_fallback_dominance,
                )
                artist_lang[artist_name] = voted_lang or "en"
            locale_signal_count += 1
            continue

        if detected_lang and detected_conf >= fallback_fasttext_threshold:
            artist_lang[artist_name] = detected_lang
        else:
            voted_lang = _vote_language_from_titles(
                model,
                cleaned_titles,
                conf_floor=vote_fallback_conf_floor,
                min_votes=vote_fallback_min_votes,
                dominance=vote_fallback_dominance,
            )
            artist_lang[artist_name] = voted_lang or "en"
        fallback_count += 1

    if verbose:
        print(
            "Language resolution stats: "
            f"genre-override={override_count:,}, "
            f"tag-lang={explicit_tag_count:,}, "
            f"locale-signal={locale_signal_count:,}, "
            f"default/fallback={fallback_count:,}"
        )

    return artist_lang
