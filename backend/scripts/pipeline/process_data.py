#!/usr/bin/env python3
"""
Process filtered Spotify data into split serving datasets.

Pure Polars implementation - optimized for 800MB RAM VPS.
No Pandas conversion = ~2-3x lower peak memory.
Merging of additional data is handled by filter_data.py.

Usage:
    # Default paths from paths.py
    python process_data.py
    
    # Custom paths
    python process_data.py -i filtered.parquet
    python process_data.py --tracks-output tracks.parquet --artists-output artists.parquet

Memory profile:
    - Previous (Polars→Pandas→Polars): ~500-600MB peak
    - Current (Pure Polars): ~150-250MB peak
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from paths import (
    FILTERED_DATASET,
    TRACKS_DATASET,
    ARTISTS_DATASET,
    get_filtered_dataset,
)
from io_utils import (
    read_input_file,
    atomic_write_parquet,
    validate_tracks_dataset,
    validate_artists_dataset,
    update_manifest,
    save_scaler_params,
)
from pipeline.utils import (
    compute_genre_embeddings_polars,
    apply_inter_artist_smearing,
    resolve_artist_languages,
    minmax_scale_polars,
)
from track_dedup import deduplicate_tracks_polars


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process filtered Spotify song data into split serving datasets (Pure Polars).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=None,
        help="Path to input file (parquet or csv). Default: auto from paths.py",
    )
    parser.add_argument(
        "--tracks-output",
        type=Path,
        default=None,
        help="Path to tracks output parquet file. Default: tracks.parquet",
    )
    parser.add_argument(
        "--artists-output",
        type=Path,
        default=None,
        help="Path to artists output parquet file. Default: artists.parquet",
    )
    parser.add_argument(
        "--cap",
        type=int,
        default=50,
        help="Maximum songs for the most popular artists",
    )
    parser.add_argument(
        "--floor",
        type=int,
        default=20,
        help="Maximum songs for the least popular artists",
    )
    parser.add_argument(
        "--max-artists",
        type=int,
        default=0,
        help="Keep only the top N most popular artists (0 = no limit)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed processing info",
    )
    parser.add_argument(
        "--smear-strength",
        type=float,
        default=0.6,
        help="Strength of inter-artist genre smearing (0.0 to 1.0)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Dev mode: use fast compression (zstd level 1 instead of 22)",
    )
    parser.add_argument(
        "--english-pct",
        type=float,
        default=75.0,
        help="Target English percentage after language shaping (e.g., 75 for 75%%)",
    )
    parser.add_argument(
        "--no-shaping",
        action="store_true",
        help="Disable language shaping entirely (keep original distribution)",
    )
    parser.add_argument(
        "--min-lang-artists",
        type=int,
        default=100,
        help="Drop non-English languages with fewer than N artists (too few for useful recommendations)",
    )
    return parser.parse_args()


def log(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg)


def _allocate_language_counts(
    scaled: np.ndarray,
    upper_bounds: np.ndarray,
    target_total: int,
) -> np.ndarray:
    """Allocate integer per-language keeps with 1..upper_bounds and exact target sum."""
    alloc = np.floor(np.clip(scaled, 1.0, upper_bounds)).astype(np.int64)
    current_total = int(alloc.sum())

    if current_total < target_total:
        need = target_total - current_total
        room = upper_bounds.astype(np.int64, copy=False) - alloc
        frac = scaled - np.floor(scaled)
        frac = np.where(room > 0, frac, -np.inf)
        while need > 0 and np.any(room > 0):
            order = np.argsort(frac)[::-1]
            progressed = False
            for idx in order:
                if need == 0:
                    break
                if room[idx] <= 0:
                    continue
                alloc[idx] += 1
                room[idx] -= 1
                need -= 1
                progressed = True
            if not progressed:
                break
            frac = np.where(room > 0, frac, -np.inf)
    elif current_total > target_total:
        need = current_total - target_total
        removable = alloc - 1
        penalty = alloc - scaled
        penalty = np.where(removable > 0, penalty, np.inf)
        while need > 0 and np.any(removable > 0):
            order = np.argsort(penalty)
            progressed = False
            for idx in order:
                if need == 0:
                    break
                if removable[idx] <= 0:
                    continue
                alloc[idx] -= 1
                removable[idx] -= 1
                need -= 1
                progressed = True
            if not progressed:
                break
            penalty = np.where(removable > 0, penalty, np.inf)

    return alloc


def _shape_non_english_by_artist(
    df: pl.DataFrame,
    english_pct: float,
    verbose: bool,
    min_lang_artists: int = 10,
) -> pl.DataFrame:
    """Reduce non-English share by removing whole non-English artists.

    This preserves per-artist track cohorts (instead of trimming individual tracks),
    which avoids collapsing artists toward very low post-shaping track counts.

    Languages with fewer than min_lang_artists artists are dropped entirely
    (too few for useful recommendations).
    """
    intl_mask = pl.col("_language_iso") != "en"
    n_total = len(df)
    if n_total == 0:
        return df

    n_en = df.filter(~intl_mask).height
    n_intl = n_total - n_en
    current_en_pct = (n_en / n_total * 100.0) if n_total else 100.0

    # Drop languages with too few artists before shaping
    if min_lang_artists > 1:
        lang_artist_counts = (
            df.filter(intl_mask)
            .group_by("_language_iso")
            .agg(pl.col("artist_name").n_unique().alias("_n_artists"))
        )
        small_langs = (
            lang_artist_counts
            .filter(pl.col("_n_artists") < min_lang_artists)
            .select("_language_iso")
        )
        if small_langs.height > 0:
            small_lang_list = small_langs["_language_iso"].to_list()
            n_before_lang_prune = len(df)
            df = df.filter(
                (~intl_mask) | ~pl.col("_language_iso").is_in(small_lang_list)
            )
            n_lang_pruned = n_before_lang_prune - len(df)
            kept_langs = lang_artist_counts.filter(pl.col("_n_artists") >= min_lang_artists)
            log(
                f"Language min-artist filter ({min_lang_artists}): dropped {len(small_lang_list)} languages "
                f"({n_lang_pruned:,} tracks), kept {kept_langs.height} non-English languages",
                verbose,
            )
            # Recompute after pruning
            n_total = len(df)
            n_en = df.filter(~intl_mask).height
            n_intl = n_total - n_en
            current_en_pct = (n_en / n_total * 100.0) if n_total else 100.0

    if current_en_pct >= english_pct or n_intl <= 0:
        log(
            f"Language shaping not needed: English share {current_en_pct:.1f}% >= {english_pct}%",
            verbose,
        )
        return df

    # Keep all English tracks fixed and solve target non-English track budget.
    target_intl_raw = n_en * (100.0 - english_pct) / english_pct

    intl_artist_stats = (
        df.filter(intl_mask)
        .group_by(["artist_name", "_language_iso"])
        .agg([
            pl.len().alias("_artist_tracks"),
            pl.col("popularity").max().alias("_artist_pop"),
        ])
    )
    if intl_artist_stats.is_empty():
        return df

    # Per-language non-English track totals (artist-granular shaping budgets).
    lang_counts = (
        intl_artist_stats
        .group_by("_language_iso")
        .agg(pl.col("_artist_tracks").sum().alias("count"))
        .sort("count", descending=True)
    )
    lang_names = lang_counts["_language_iso"].to_list()
    lang_orig = np.array(lang_counts["count"].to_list(), dtype=np.int64)
    n_languages = len(lang_names)

    target_intl = int(round(target_intl_raw))
    target_intl = max(n_languages, min(n_intl, target_intl))

    lo, hi = 0.01, 1.0
    for _ in range(64):
        mid = (lo + hi) / 2.0
        shaped = np.power(lang_orig.astype(np.float64), mid)
        total_shaped = shaped.sum()
        if total_shaped <= 0:
            lo = mid
            continue
        scaled = shaped * (target_intl / total_shaped)
        clipped = np.clip(scaled, 1.0, lang_orig)
        predicted_total = clipped.sum()
        if predicted_total > target_intl:
            hi = mid
        else:
            lo = mid

    alpha = (lo + hi) / 2.0
    shaped = np.power(lang_orig.astype(np.float64), alpha)
    total_shaped = shaped.sum()
    if total_shaped > 0:
        scaled = shaped * (target_intl / total_shaped)
    else:
        scaled = np.ones_like(lang_orig)

    alloc = _allocate_language_counts(
        scaled=scaled,
        upper_bounds=lang_orig,
        target_total=target_intl,
    )

    keep_intl_artists: set[str] = set()
    for lang, track_budget in zip(lang_names, alloc.tolist()):
        lang_artists = (
            intl_artist_stats
            .filter(pl.col("_language_iso") == lang)
            .sort(["_artist_pop", "_artist_tracks"], descending=[True, True])
            .with_columns(pl.col("_artist_tracks").cum_sum().alias("_cum_tracks"))
        )

        kept = lang_artists.filter(pl.col("_cum_tracks") <= track_budget).select("artist_name")
        if kept.height == 0 and lang_artists.height > 0:
            kept = lang_artists.head(1).select("artist_name")

        keep_intl_artists.update(kept["artist_name"].to_list())

    if keep_intl_artists:
        shaped_df = df.filter((~intl_mask) | pl.col("artist_name").is_in(list(keep_intl_artists)))
    else:
        shaped_df = df.filter(~intl_mask)

    new_n_intl = shaped_df.filter(intl_mask).height
    new_en_pct = shaped_df.filter(~intl_mask).height / len(shaped_df) * 100.0 if len(shaped_df) else 0.0

    intl_artists_before = int(intl_artist_stats.select(pl.col("artist_name").n_unique().alias("n"))["n"][0])
    intl_artists_after = int(
        shaped_df
        .filter(intl_mask)
        .select(pl.col("artist_name").n_unique().alias("n"))["n"][0]
    )

    log(
        f"Language shaping (artist-level, α={alpha:.3f}): removed {n_intl - new_n_intl:,} non-English tracks "
        f"and {intl_artists_before - intl_artists_after:,} non-English artists "
        f"({current_en_pct:.1f}% -> {new_en_pct:.1f}% English)",
        verbose,
    )

    return shaped_df


def load_and_merge_data(
    input_path: Path,
    verbose: bool,
) -> tuple[pl.LazyFrame, int]:
    """
    Load data using Polars LazyFrame for memory efficiency.
    
    Returns a LazyFrame - operations are not executed until .collect() is called.
    This allows Polars to optimize the entire query plan.
    """
    log(f"Loading data from {input_path}...", verbose)
    
    # Read with schema normalization
    df = read_input_file(input_path, normalize_schema=True)
    
    # Remove pandas index artifact if present
    if "Unnamed: 0" in df.columns:
        df = df.drop("Unnamed: 0")
    
    n_initial = len(df)
    log(f"Loaded {n_initial:,} songs", verbose)
    
    # Note: Null filtering for required fields (artist_name, track_name, track_id)
    # is done in filter_data.py as the first filtering step.
    # If processing unfiltered data, add a defensive check here.
    
    if verbose:
        mem_mb = df.estimated_size() / (1024 * 1024)
        print(f"  Polars memory: {mem_mb:.1f} MB")
    
    return df.lazy(), n_initial


def process_data(
    input_path: Path | None,
    tracks_output_path: Path,
    artists_output_path: Path,
    cap: int,
    floor: int,
    max_artists: int,
    english_pct: float,
    no_shaping: bool,
    smear_strength: float,
    verbose: bool,
    dev: bool = False,
    input_df: pl.DataFrame | None = None,
    min_lang_artists: int = 10,
) -> None:
    """Main processing pipeline - Pure Polars implementation.
    
    If input_df is provided, uses it directly instead of reading from disk.
    """
    if cap <= 0 or floor <= 0:
        raise ValueError("--cap and --floor must both be positive integers")
    if floor > cap:
        raise ValueError("--floor cannot be greater than --cap")
    if not no_shaping and not (0.0 < english_pct < 100.0):
        raise ValueError("--english-pct must be between 0 and 100 (exclusive)")
    
    if input_df is not None:
        n_initial = len(input_df)
        log(f"Using in-memory DataFrame: {n_initial:,} songs", verbose)
        lf = input_df.lazy()
    else:
        lf, n_initial = load_and_merge_data(input_path, verbose)
    
    # Define columns
    num_cols = [
        "year", "key", "popularity", "acousticness", "danceability", "duration_ms",
        "energy", "instrumentalness", "liveness", "loudness", "speechiness", "tempo",
        "valence", "time_signature"
    ]
    
    # Collect to get column list (minimal overhead)
    df = lf.collect()
    num_cols = [c for c in num_cols if c in df.columns]
    
    # Fill NaNs for specific columns
    fill_exprs = []
    if "year" in df.columns:
        fill_exprs.append(pl.col("year").fill_null(2020))
    if "popularity" in df.columns:
        fill_exprs.append(pl.col("popularity").fill_null(25))
    
    if fill_exprs:
        df = df.with_columns(fill_exprs)
    
    # Fill remaining nulls with column means.
    # Some external-first datasets can have entire numeric columns null
    # (e.g., when schema-normalized from sparse sources). In that case,
    # Polars mean() returns None; fall back to 0.0 to keep processing stable.
    for col in num_cols:
        if col not in ["year", "popularity"]:
            mean_val = df[col].mean()
            if mean_val is None:
                mean_val = 0.0
            df = df.with_columns(pl.col(col).fill_null(mean_val))
    
    log(f"Scaling {len(num_cols)} numeric columns", verbose)
    
    # Compute and save scaler parameters before scaling
    scaler_params = {}
    for col in num_cols:
        min_val = df[col].min()
        max_val = df[col].max()
        scaler_params[col] = (float(min_val), float(max_val))
    
    # Apply min-max scaling (Pure Polars)
    df = minmax_scale_polars(df.lazy(), num_cols).collect()
    
    # Save scaler params for incremental updates
    save_scaler_params(scaler_params)
    
    # Cast to float32 after scaling
    df = df.with_columns([pl.col(c).cast(pl.Float32) for c in num_cols])

    # Validate required columns
    if "artist_name" not in df.columns or "popularity" not in df.columns:
        print("Error: Required columns 'artist_name' and 'popularity' are missing.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate tracks per artist (Pure Polars implementation)
    n_before_dedup = len(df)
    df = deduplicate_tracks_polars(df)
    n_dedup_removed = n_before_dedup - len(df)
    log(f"Name-based dedup: {n_dedup_removed:,} removed, {len(df):,} remaining", verbose)
    if verbose:
        n_artists_before = n_before_dedup  # approx, tracks not artists
        log(f"  ({n_dedup_removed / n_before_dedup * 100:.1f}% of pre-dedup tracks were duplicates)", verbose)

    # Enforce non-null genre rows in encoded output
    if "genre" in df.columns:
        n_null_genre = df["genre"].null_count()
        if n_null_genre > 0:
            df = df.filter(pl.col("genre").is_not_null())
            log(f"Dropped {n_null_genre:,} tracks with null genre", verbose)

    # Canonicalize artist casing/spacing variants
    artist_key_expr = (
        pl.col("artist_name")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .str.strip_chars()
        .str.replace_all(r"\s+", " ", literal=False)
    )
    df = df.with_columns(artist_key_expr.alias("_artist_key"))

    canonical_names = (
        df.group_by(["_artist_key", "artist_name"])
        .agg([
            pl.col("popularity").max().alias("_artist_max_pop"),
            pl.len().alias("_artist_rows"),
        ])
        .sort(["_artist_key", "_artist_max_pop", "_artist_rows"], descending=[False, True, True])
        .unique(subset=["_artist_key"], keep="first")
        .select(["_artist_key", pl.col("artist_name").alias("_artist_canonical")])
    )
    df = df.join(canonical_names, on="_artist_key", how="left")
    n_artist_canonicalized = df.filter(pl.col("artist_name") != pl.col("_artist_canonical")).height
    df = df.with_columns(pl.col("_artist_canonical").alias("artist_name")).drop("_artist_canonical")
    if verbose and n_artist_canonicalized > 0:
        log(f"Artist name canonicalization (case/spacing): {n_artist_canonicalized:,} tracks updated", verbose)

    if "_artist_key" in df.columns:
        df = df.drop("_artist_key")

    # Resolve final language per artist and attach language column
    artist_lang = resolve_artist_languages(df, verbose=verbose)
    if not artist_lang:
        raise RuntimeError("Language resolution produced no artist mappings")

    artist_lang_df = pl.DataFrame(
        {
            "artist_name": list(artist_lang.keys()),
            "_language_iso": list(artist_lang.values()),
        }
    )
    df = df.join(artist_lang_df, on="artist_name", how="left")
    df = df.with_columns(pl.col("_language_iso").fill_null("en"))

    # Language shaping: artist-level pruning to hit target English percentage
    if not no_shaping:
        df = _shape_non_english_by_artist(df, english_pct, verbose, min_lang_artists=min_lang_artists)
    else:
        log("Language shaping disabled (--no-shaping)", verbose)

    # Keep only top N artists, allocated proportionally per language to preserve mix.
    if max_artists > 0:
        n_before_artist_limit = len(df)
        artist_summary = (
            df.group_by("artist_name")
            .agg([
                pl.col("popularity").max().alias("_artist_max_pop"),
                pl.col("_language_iso").first().alias("_lang"),
            ])
        )
        total_artists = len(artist_summary)
        if total_artists > max_artists:
            # Allocate slots proportionally to each language
            lang_counts = artist_summary.group_by("_lang").agg(pl.len().alias("_n"))
            lang_names_l = lang_counts["_lang"].to_list()
            lang_n = np.array(lang_counts["_n"].to_list(), dtype=np.int64)
            raw_alloc = lang_n * (max_artists / total_artists)
            # Floor allocate, then distribute remainder by fractional part
            int_alloc = np.floor(raw_alloc).astype(np.int64)
            int_alloc = np.maximum(int_alloc, 1)  # every language keeps at least 1
            remainder = max_artists - int(int_alloc.sum())
            if remainder > 0:
                fracs = raw_alloc - int_alloc
                bump_order = np.argsort(fracs)[::-1]
                for idx in bump_order[:remainder]:
                    int_alloc[idx] += 1
            elif remainder < 0:
                # Over-allocated due to min-1 guarantees; trim from largest groups
                excess = -remainder
                trim_order = np.argsort(int_alloc)[::-1]
                for idx in trim_order:
                    if excess <= 0:
                        break
                    can_trim = int(int_alloc[idx]) - 1
                    trim = min(can_trim, excess)
                    int_alloc[idx] -= trim
                    excess -= trim

            # Select top artists per language by popularity
            keep_parts = []
            for lang, n_keep in zip(lang_names_l, int_alloc.tolist()):
                lang_artists = (
                    artist_summary.filter(pl.col("_lang") == lang)
                    .sort("_artist_max_pop", descending=True)
                    .head(n_keep)
                    .select("artist_name")
                )
                keep_parts.append(lang_artists)
            keep_artists = pl.concat(keep_parts)
            df = df.join(keep_artists, on="artist_name", how="semi")
        log(
            f"Artist limit ({max_artists}): kept {df['artist_name'].n_unique():,} artists, "
            f"removed {n_before_artist_limit - len(df):,} tracks",
            verbose,
        )

    # Popularity-shaped per-artist track cap
    # Top-popularity artists get `cap`, bottom get `floor`, smooth interpolation between
    n_before_cap = len(df)
    artist_pop = (
        df.group_by("artist_name")
        .agg(pl.col("popularity").max().alias("_artist_pop"))
    )
    pop_min = artist_pop["_artist_pop"].min()
    pop_max = artist_pop["_artist_pop"].max()
    pop_range = pop_max - pop_min if pop_max > pop_min else 1.0

    artist_pop = artist_pop.with_columns(
        (
            pl.lit(floor)
            + (pl.col("_artist_pop") - pl.lit(pop_min)) / pl.lit(pop_range) * pl.lit(cap - floor)
        )
        .round(0)
        .cast(pl.Int32)
        .alias("_artist_cap")
    )
    df = df.join(artist_pop.select("artist_name", "_artist_cap"), on="artist_name", how="left")
    df = (
        df
        .sort("popularity", descending=True)
        .with_columns(
            pl.col("popularity")
            .rank("ordinal", descending=True)
            .over("artist_name")
            .alias("_rank")
        )
        .filter(pl.col("_rank") <= pl.col("_artist_cap"))
        .drop("_rank", "_artist_cap")
    )
    n_cap_removed = n_before_cap - len(df)

    log(f"Artist cap ({floor}-{cap}/artist): {n_cap_removed:,} removed, {len(df):,} remaining", verbose)
    if verbose:
        n_artists_final = df["artist_name"].n_unique()
        log(f"  Artists: {n_artists_final:,} unique artists after cap", verbose)

    # Audio features (scaled 0-1, retained in tracks.parquet)
    feature_cols = [
        "popularity", "year", "duration_ms",
        "acousticness", "danceability", "energy", "instrumentalness",
        "liveness", "loudness", "speechiness", "tempo", "valence"
    ]

    # Process genre embeddings after shaping/limits to reduce work.
    genre_cols = []
    if "genre" in df.columns:
        log("Computing smart family embeddings...", verbose)
        unique_genres = df["genre"].drop_nulls().unique().to_list()
        embedding_df = compute_genre_embeddings_polars(unique_genres)

        df = df.join(embedding_df, on="genre", how="left")
        genre_cols = [c for c in embedding_df.columns if c.startswith("genre_")]
        df = df.with_columns([
            pl.col(c).fill_null(0.0).cast(pl.Float32) for c in genre_cols
        ])
        df = apply_inter_artist_smearing(
            df,
            embedding_df,
            genre_cols,
            smear_strength,
            verbose=verbose,
        )

    df = df.with_columns(pl.col("_language_iso").fill_null("en").cast(pl.Utf8).alias("language"))
    df = df.drop("_language_iso")

    # Enforce no null genre/language in artist-level output source rows
    n_before_artist_null_guard = len(df)
    df = df.filter(pl.col("genre").is_not_null() & pl.col("language").is_not_null())
    n_removed_artist_null_guard = n_before_artist_null_guard - len(df)
    if n_removed_artist_null_guard > 0:
        log(
            f"Dropped {n_removed_artist_null_guard:,} track rows due to null genre/language before split",
            verbose,
        )

    # Build artist-level table (single row per artist)
    artist_agg_exprs = [
        pl.col("genre")
        .drop_nulls()
        .sort_by("popularity", descending=True)
        .first()
        .alias("genre"),
        pl.col("language").drop_nulls().first().alias("language"),
    ]
    artist_agg_exprs.extend(pl.col(c).mean().alias(c) for c in genre_cols)

    artists_df = df.group_by("artist_name").agg(artist_agg_exprs)
    artists_df = artists_df.filter(pl.col("genre").is_not_null() & pl.col("language").is_not_null())

    # Keep only tracks that have a valid artist row (strict non-null artist metadata policy)
    tracks_df = (
        df.join(
            artists_df.select("artist_name"),
            on="artist_name",
            how="semi",
        )
    )

    # Build final tracks table (no per-track genre/language embeddings)
    tracks_cols = ["artist_name", "track_name", "track_id"] + [c for c in feature_cols if c in tracks_df.columns]
    tracks_df = tracks_df.select(tracks_cols)

    # Cast numeric outputs to float32 for memory efficiency
    track_float_cols = [c for c in tracks_df.columns if tracks_df[c].dtype in [pl.Float32, pl.Float64]]
    if track_float_cols:
        tracks_df = tracks_df.with_columns([pl.col(c).cast(pl.Float32) for c in track_float_cols])
    if genre_cols:
        artists_df = artists_df.with_columns([pl.col(c).cast(pl.Float32) for c in genre_cols])

    langs = sorted(artists_df["language"].drop_nulls().unique().to_list())

    if verbose:
        tracks_mem_mb = tracks_df.estimated_size() / (1024 * 1024)
        artists_mem_mb = artists_df.estimated_size() / (1024 * 1024)
        print(f"Memory usage (final): tracks={tracks_mem_mb:.1f} MB, artists={artists_mem_mb:.1f} MB")

    # Atomic writes with validation
    compression_level = 1 if dev else 22
    if dev:
        print("[DEV MODE] Using fast compression (zstd level 1)")
    log(f"Writing tracks to {tracks_output_path}...", verbose)
    atomic_write_parquet(
        tracks_df,
        tracks_output_path,
        compression="zstd",
        compression_level=compression_level,
        validate=validate_tracks_dataset,
        verbose=verbose,
    )
    log(f"Writing artists to {artists_output_path}...", verbose)
    atomic_write_parquet(
        artists_df,
        artists_output_path,
        compression="zstd",
        compression_level=compression_level,
        validate=validate_artists_dataset,
        verbose=verbose,
    )
    
    # Update manifest
    update_manifest(
        operation="full_process",
        track_count=len(tracks_df),
        artist_count=len(artists_df),
        extra={
            "language_codebook": None,
            "language_count": len(langs),
            "serving_tracks_file": tracks_output_path.name,
            "serving_artists_file": artists_output_path.name,
        },
    )

    # Summary
    print(f"\nProcessed {n_initial:,} -> {len(tracks_df):,} songs")
    print(f"Artists: {len(artists_df):,}")
    print(f"Tracks output:  {tracks_output_path}")
    print(f"Artists output: {artists_output_path}")


def main() -> None:
    args = parse_args()
    
    # Resolve input path
    if args.input:
        input_path = args.input
    else:
        try:
            input_path = get_filtered_dataset()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            print("Run filter_data.py first or specify --input", file=sys.stderr)
            sys.exit(1)
    
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    # Resolve output paths
    tracks_output_path = args.tracks_output or TRACKS_DATASET
    artists_output_path = args.artists_output or ARTISTS_DATASET
    
    process_data(
        input_path=input_path,
        tracks_output_path=tracks_output_path,
        artists_output_path=artists_output_path,
        cap=args.cap,
        floor=args.floor,
        max_artists=args.max_artists,
        english_pct=args.english_pct,
        no_shaping=args.no_shaping,
        smear_strength=args.smear_strength,
        verbose=args.verbose,
        dev=args.dev,
        min_lang_artists=args.min_lang_artists,
    )


if __name__ == "__main__":
    main()
