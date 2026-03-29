#!/usr/bin/env python3
"""
Inspect external genre tags and resolved override genre for artists.

Usage:
    python debug_genre_lookup.py "Flor" "MGMT"
    python debug_genre_lookup.py --names "Flor, MGMT"
    python debug_genre_lookup.py --file artists.txt
    python debug_genre_lookup.py --lang "Daft Punk" "Stromae" "Phoenix"
"""

from __future__ import annotations

import argparse
from collections import Counter
import sys
import time
from pathlib import Path

import polars as pl

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from genre_mapping import (
    explain_artist_tags,
    explain_raw_genre,
)
from paths import TRACKS_DATASET, get_genre_sources
from language_detection import load_fasttext_model, clean_track_title, detect_language
from language_config import (
    GENRE_LANG_OVERRIDES,
    LANGUAGE_MAX_TITLES,
    TAG_FASTTEXT_THRESHOLD,
    CJK_TAG_FASTTEXT_THRESHOLD,
    LOCALE_SIGNAL_FASTTEXT_THRESHOLD,
    FALLBACK_FASTTEXT_THRESHOLD,
    VOTE_FALLBACK_CONF_FLOOR,
    VOTE_FALLBACK_MIN_VOTES,
    VOTE_FALLBACK_DOMINANCE,
)
from track_dedup import normalize_artist_name


def parse_names(args: argparse.Namespace) -> list[str]:
    names: list[str] = []
    if args.names:
        names.extend([n.strip() for n in args.names.split(",") if n.strip()])
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            raise FileNotFoundError(f"Names file not found: {file_path}")
        for line in file_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                names.append(stripped)
    if args.positional:
        names.extend([n.strip() for n in args.positional if n.strip()])
    return list(dict.fromkeys(names))


def load_source_rows(path: Path, normalized_names: set[str]) -> pl.DataFrame | None:
    if not path.exists():
        print(f"  Not found: {path}")
        return None
    df = pl.read_parquet(path)
    df = df.with_columns(
        pl.col("name")
        .cast(pl.Utf8)
        .map_elements(normalize_artist_name, return_dtype=pl.Utf8)
        .alias("_norm")
    )
    return df.filter(pl.col("_norm").is_in(list(normalized_names)))


def summarize_rows(df: pl.DataFrame, label: str, *, all_matches: bool = False) -> None:
    if df is None or df.is_empty():
        print(f"  {label}: no matching rows")
        return

    if not all_matches:
        # Default view: one best row per normalized name, highest popularity.
        df = (
            df.with_columns(pl.col("popularity").fill_null(0).cast(pl.Int64).alias("_pop"))
            .sort("_pop", descending=True)
            .unique(subset=["_norm"], keep="first")
            .drop("_pop")
        )

    print(f"  {label}:")
    for row in df.to_dicts():
        name = row.get("name")
        tags = row.get("genres") or []
        fallback = row.get("fallback")
        artist_explain = explain_artist_tags(tags)
        artist_result = artist_explain["result"]

        if artist_result is None:
            artist_result_str = "None"
        else:
            artist_result_str = artist_result

        votes = artist_explain.get("votes") or {}
        vote_str = ", ".join(f"{g}:{c}" for g, c in sorted(votes.items(), key=lambda kv: (-kv[1], kv[0])))
        if not vote_str:
            vote_str = "none"

        print(f"    - name: {name}")
        if row.get("popularity") is not None:
            print(f"      popularity: {row.get('popularity')}")
        if fallback:
            print(f"      fallback: {fallback}")
        print(f"      raw_genres: {tags}")
        print(f"      map_artist_tags: {artist_result_str}")
        tag_lang = artist_explain.get("tag_lang")
        if tag_lang:
            print(f"      tag_lang: {tag_lang}")
        print(f"      votes: {vote_str}")
        print("      per-tag mapping:")
        for tag in tags:
            explained = explain_raw_genre(tag)
            mapped = explained.get("mapped_genre")
            reason = explained.get("reason")
            if mapped:
                print(f"        {tag} -> {mapped} ({reason})")
            else:
                print(f"        {tag} -> None ({reason})")


def _build_filtered_lookup(normalized_names: set[str]) -> tuple[dict[str, str], dict[str, str], dict[str, bool]]:
    """Build genre lookup for specific normalized names only (fast path for debug).

    Uses the same sequential source priority as load_artist_genre_lookup
    (paths.get_genre_sources()), most popular entry per name, early stopping.
    """
    from genre_mapping import (
        _map_standard_genre,
        map_artist_tags_with_lang_signal,
    )

    lookup: dict[str, str] = {}
    tag_lang_lookup: dict[str, str] = {}
    tag_signal_lookup: dict[str, bool] = {}

    for source in get_genre_sources():
        path = source.path
        if not path.exists():
            continue

        remaining = normalized_names - set(lookup.keys())
        if not remaining:
            break

        df = pl.read_parquet(path)
        df = df.with_columns(
            pl.col("name")
            .cast(pl.Utf8)
            .map_elements(normalize_artist_name, return_dtype=pl.Utf8)
            .alias("_norm")
        )
        df = df.filter(pl.col("_norm").is_in(list(remaining)))

        if df.is_empty():
            continue

        # Keep only the most popular row per normalized name
        df = (
            df.with_columns(pl.col("popularity").fill_null(0).cast(pl.Int64).alias("_pop"))
            .sort("_pop", descending=True)
            .unique(subset=["_norm"], keep="first")
            .drop("_pop")
        )

        for row in df.iter_rows(named=True):
            norm_name = row["_norm"]
            tags = row.get("genres") or []

            genre, tag_lang, has_locale_signal = map_artist_tags_with_lang_signal(tags)
            if not genre:
                fallback = row.get("fallback")
                if fallback and isinstance(fallback, str):
                    genre = _map_standard_genre(fallback.strip().lower())
            if genre:
                lookup[norm_name] = genre
            if tag_lang:
                tag_lang_lookup[norm_name] = tag_lang
            if has_locale_signal or tag_lang is not None:
                tag_signal_lookup[norm_name] = True

    return lookup, tag_lang_lookup, tag_signal_lookup


# ---- Language detection helpers ----
def _load_fasttext_model():
    """Load the FastText language-identification model and return (model, load_seconds)."""
    start = time.perf_counter()
    model = load_fasttext_model()
    load_s = time.perf_counter() - start
    return model, load_s


def _clean_title(title: str) -> str:
    return clean_track_title(title)


def _detect(model, text: str | None) -> tuple[str, float | None]:
    """Detect language of text using FastText. Returns (iso_code, confidence) or ('unknown', None)."""
    if not text or not text.strip():
        return "unknown", None

    code, conf = detect_language(model, text)
    if not code:
        return "unknown", None
    conf = round(float(conf), 4)
    return code, conf


def _vote_language_from_title_results(
    title_results: list[tuple[str, str, float | None]],
    *,
    conf_floor: float,
    min_votes: int,
    dominance: float,
) -> str | None:
    votes: Counter[str] = Counter()
    for _title, lang, conf in title_results:
        if lang == "unknown":
            continue
        if conf is None or conf < conf_floor:
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


def run_language_detection(
    names: list[str],
    normalized: set[str],
    *,
    max_titles: int,
    genre_lookup: dict[str, str] | None = None,
    tag_lang_lookup: dict[str, str] | None = None,
    tag_signal_lookup: dict[str, bool] | None = None,
) -> None:
    """Run language detection on track titles for the given artists."""
    from collections import Counter

    if not TRACKS_DATASET.exists():
        print(f"\n  Language detection skipped: {TRACKS_DATASET} not found")
        return

    print("\n" + "=" * 60)
    print("LANGUAGE DETECTION (fasttext)")
    print("=" * 60)

    model, load_s = _load_fasttext_model()
    print(f"  Model loaded in {load_s:.2f}s")

    genre_lookup = genre_lookup or {}
    tag_lang_lookup = tag_lang_lookup or {}
    tag_signal_lookup = tag_signal_lookup or {}

    # Load tracks for these artists
    norm_list = list(normalized)
    df = (
        pl.scan_parquet(TRACKS_DATASET)
        .filter(pl.col("artist_name").is_not_null())
        .select(["artist_name", "track_name", "popularity"])
        .collect()
    )
    # Normalize artist names for matching
    df = df.with_columns(
        pl.col("artist_name")
        .cast(pl.Utf8)
        .map_elements(normalize_artist_name, return_dtype=pl.Utf8)
        .alias("_norm")
    )
    df = df.filter(pl.col("_norm").is_in(norm_list))

    if df.is_empty():
        print("  No tracks found in encoded dataset for these artists.")
        return

    total_texts = 0
    detect_start = time.perf_counter()

    for name in names:
        norm = normalize_artist_name(name)
        artist_df = df.filter(pl.col("_norm") == norm)
        if artist_df.is_empty():
            print(f"\n  {name}: no tracks in dataset")
            continue

        track_count = artist_df.height
        # Match pipeline resolver defaults for consistent diagnostics (configurable).
        sample_df = artist_df.sort("popularity", descending=True).head(max_titles)
        titles = [
            row["track_name"]
            for row in sample_df.iter_rows(named=True)
            if row["track_name"] and isinstance(row["track_name"], str)
        ]

        # Detect on artist name
        name_lang, name_conf = _detect(model, name)

        # Detect on individual titles
        title_results: list[tuple[str, str, float | None]] = []
        title_votes: Counter = Counter()
        for title in titles:
            cleaned = _clean_title(title)
            lang, conf = _detect(model, cleaned)
            title_results.append((title, lang, conf))
            title_votes[lang] += 1
            total_texts += 1

        # Detect on combined text (all sampled titles joined)
        combined = " | ".join(_clean_title(t) for t in titles)
        combined_lang, combined_conf = _detect(model, combined)
        total_texts += 1

        resolved_genre = genre_lookup.get(norm)
        tag_lang = tag_lang_lookup.get(norm)
        has_tag_signal = bool(tag_lang) or bool(tag_signal_lookup.get(norm))
        override_lang = GENRE_LANG_OVERRIDES.get(resolved_genre) if resolved_genre else None

        voted_lang = _vote_language_from_title_results(
            title_results,
            conf_floor=VOTE_FALLBACK_CONF_FLOOR,
            min_votes=VOTE_FALLBACK_MIN_VOTES,
            dominance=VOTE_FALLBACK_DOMINANCE,
        )

        final_lang = "en"
        decision_path = "fallback-default-en"
        effective_threshold = FALLBACK_FASTTEXT_THRESHOLD

        if override_lang:
            final_lang = override_lang
            decision_path = f"genre-override ({resolved_genre})"
            effective_threshold = None
        elif tag_lang:
            effective_threshold = (
                CJK_TAG_FASTTEXT_THRESHOLD if tag_lang in {"ja", "ko", "zh"} else TAG_FASTTEXT_THRESHOLD
            )
            if combined_lang != "unknown" and combined_conf is not None and combined_conf >= effective_threshold:
                final_lang = combined_lang
                decision_path = "tag-signal + fasttext override"
            else:
                final_lang = tag_lang
                decision_path = "tag-lang fallback"
        elif has_tag_signal:
            effective_threshold = LOCALE_SIGNAL_FASTTEXT_THRESHOLD
            if combined_lang != "unknown" and combined_conf is not None and combined_conf >= LOCALE_SIGNAL_FASTTEXT_THRESHOLD:
                final_lang = combined_lang
                decision_path = "locale-signal + fasttext override"
            elif voted_lang:
                final_lang = voted_lang
                decision_path = "locale-signal + vote fallback"
            else:
                final_lang = "en"
                decision_path = "locale-signal fallback"
        else:
            effective_threshold = FALLBACK_FASTTEXT_THRESHOLD
            if combined_lang != "unknown" and combined_conf is not None and combined_conf >= FALLBACK_FASTTEXT_THRESHOLD:
                final_lang = combined_lang
                decision_path = "fallback fasttext override"
            elif voted_lang:
                final_lang = voted_lang
                decision_path = "fallback vote override"

        # Determine dominant language
        # Filter out 'unknown' for dominant calc
        known_votes = {k: v for k, v in title_votes.items() if k != "unknown"}
        if known_votes:
            dominant = max(known_votes, key=known_votes.get)
            dominant_pct = round(known_votes[dominant] / len(titles) * 100)
        else:
            dominant = "unknown"
            dominant_pct = 0

        print(f"\n  {name} ({track_count} tracks in dataset)")
        print(f"    Artist name language: {name_lang} (conf={name_conf})")
        print(f"    Combined titles:      {combined_lang} (conf={combined_conf})")
        print(f"    Resolved genre:       {resolved_genre}")
        print(f"    tag_lang:             {tag_lang}")
        print(f"    tag_signal:           {has_tag_signal}")
        if effective_threshold is not None:
            print(f"    Effective threshold:  conf >= {effective_threshold}")
        else:
            print("    Effective threshold:  n/a (genre override)")
        print(f"    Pipeline final lang:  {final_lang} ({decision_path})")
        print(f"    Title sample size:    top {max_titles} by popularity")
        print(f"    Dominant from votes:  {dominant} ({dominant_pct}%)")
        print(f"    Title votes: {dict(title_votes.most_common())}")
        print(f"    Sample titles:")
        for title, lang, conf in title_results[:10]:
            conf_str = f"{conf:.2f}" if conf is not None else "n/a"
            marker = " !" if lang != "unknown" and lang != dominant and dominant != "unknown" else ""
            print(f"      [{lang} {conf_str}]{marker} {title}")

    detect_s = time.perf_counter() - detect_start
    if total_texts > 0:
        print(f"\n  Detection speed: {total_texts} texts in {detect_s:.2f}s "
              f"({total_texts / detect_s:.0f} texts/sec, {detect_s * 1000 / total_texts:.1f} ms/text)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug external genre lookup for artists.")
    parser.add_argument("positional", nargs="*", help="Artist names")
    parser.add_argument("--names", help="Comma-separated artist names")
    parser.add_argument("--file", help="File with artist names, one per line")
    parser.add_argument(
        "--all-matches",
        action="store_true",
        help="Show all matching rows from each source (default: show top popularity row per source and artist)",
    )
    parser.add_argument(
        "--lang",
        action="store_true",
        help="Run language detection on track titles for each artist (uses fasttext)",
    )
    parser.add_argument(
        "--max-titles",
        type=int,
        default=LANGUAGE_MAX_TITLES,
        help="Top N titles to sample for --lang (shared resolver default)",
    )
    args = parser.parse_args()

    names = parse_names(args)
    if not names:
        print("No artist names provided.")
        sys.exit(1)

    normalized = {normalize_artist_name(name) for name in names}

    # Fast path: build lookup only for requested artists instead of
    # iterating all ~1.5M rows across 3 parquets (which takes 30+ seconds).
    lookup, tag_lang_lookup, tag_signal_lookup = _build_filtered_lookup(normalized)

    print("Resolved override genres:")
    for name in names:
        norm = normalize_artist_name(name)
        resolved = lookup.get(norm)
        print(f"  {name} -> {resolved} (normalized: {norm})")

    print("\nExternal source rows:")
    for source in get_genre_sources():
        rows = load_source_rows(source.path, normalized)
        summarize_rows(rows, source.name.capitalize(), all_matches=args.all_matches)

    if args.lang:
        run_language_detection(
            names,
            normalized,
            max_titles=max(1, int(args.max_titles)),
            genre_lookup=lookup,
            tag_lang_lookup=tag_lang_lookup,
            tag_signal_lookup=tag_signal_lookup,
        )


if __name__ == "__main__":
    main()
