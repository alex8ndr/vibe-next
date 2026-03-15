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
from paths import SERKAN_GENRE, YAMAC_GENRE, VECTORQL_GENRE, ENCODED_DATASET
from language_detection import load_fasttext_model, clean_track_title, detect_language
from language_config import TAG_FASTTEXT_THRESHOLD
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


def _build_filtered_lookup(normalized_names: set[str]) -> dict[str, str]:
    """Build genre lookup for specific normalized names only (fast path for debug).

    Uses the same sequential source priority as load_artist_genre_lookup:
    Yamac → Vectorql → Serkan, most popular entry per name, early stopping.
    """
    from genre_mapping import (
        _map_standard_genre,
        map_artist_tags,
    )

    lookup: dict[str, str] = {}

    for path in [YAMAC_GENRE, VECTORQL_GENRE, SERKAN_GENRE]:
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

            genre, tag_lang = map_artist_tags(tags)
            if not genre:
                fallback = row.get("fallback")
                if fallback and isinstance(fallback, str):
                    genre = _map_standard_genre(fallback.strip().lower())
            if genre:
                lookup[norm_name] = genre

    return lookup


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
    if conf < 0.5:
        return "unknown", conf
    return code, conf


def run_language_detection(
    names: list[str],
    normalized: set[str],
    *,
    max_titles: int,
) -> None:
    """Run language detection on track titles for the given artists."""
    from collections import Counter

    if not ENCODED_DATASET.exists():
        print(f"\n  Language detection skipped: {ENCODED_DATASET} not found")
        return

    print("\n" + "=" * 60)
    print("LANGUAGE DETECTION (fasttext)")
    print("=" * 60)

    model, load_s = _load_fasttext_model()
    print(f"  Model loaded in {load_s:.2f}s")

    # Load tracks for these artists
    norm_list = list(normalized)
    df = (
        pl.scan_parquet(ENCODED_DATASET)
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
        print(f"    Pipeline threshold:   conf >= {TAG_FASTTEXT_THRESHOLD} to override tag_lang")
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
        default=30,
        help="Top N titles to sample for --lang (pipeline default is 15)",
    )
    args = parser.parse_args()

    names = parse_names(args)
    if not names:
        print("No artist names provided.")
        sys.exit(1)

    normalized = {normalize_artist_name(name) for name in names}

    # Fast path: build lookup only for requested artists instead of
    # iterating all ~1.5M rows across 3 parquets (which takes 30+ seconds).
    lookup = _build_filtered_lookup(normalized)

    print("Resolved override genres:")
    for name in names:
        norm = normalize_artist_name(name)
        resolved = lookup.get(norm)
        print(f"  {name} -> {resolved} (normalized: {norm})")

    print("\nExternal source rows:")
    serkan_rows = load_source_rows(SERKAN_GENRE, normalized)
    summarize_rows(serkan_rows, "Serkan", all_matches=args.all_matches)

    yamac_rows = load_source_rows(YAMAC_GENRE, normalized)
    summarize_rows(yamac_rows, "Yamac", all_matches=args.all_matches)

    vectorql_rows = load_source_rows(VECTORQL_GENRE, normalized)
    summarize_rows(vectorql_rows, "Vectorql", all_matches=args.all_matches)

    if args.lang:
        run_language_detection(names, normalized, max_titles=max(1, int(args.max_titles)))


if __name__ == "__main__":
    main()
