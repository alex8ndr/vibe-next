#!/usr/bin/env python3
"""
Incremental update: Append new tracks to encoded dataset without full reprocessing.

Pure Polars implementation - optimized for 800MB RAM VPS.
This is the PREFERRED low-memory update strategy (~100-200MB peak RAM).

Usage:
    # Append new tracks from added_artists.parquet
    python incremental_update.py
    
    # Specify custom source
    python incremental_update.py --source new_tracks.parquet
    
    # Dry run (show what would be added)
    python incremental_update.py --dry-run

Requirements:
    - data_encoded.parquet must already exist (run full pipeline first)
    - Source file must have same columns as raw data
    
Memory: ~100-200MB regardless of base dataset size
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent))

from paths import (
    ENCODED_DATASET,
    ADDED_ARTISTS,
    get_added_artists,
)
from io_utils import (
    read_input_file,
    read_parquet_safe,
    atomic_write_parquet,
    validate_encoded_dataset,
    update_manifest,
    load_manifest,
    load_scaler_params,
)
from genre_families import GENRE_DEFINITIONS
from track_dedup import deduplicate_tracks_polars


def compute_genre_embeddings_polars(unique_genres: list[str]) -> pl.DataFrame:
    """Compute dense embeddings for genres. Identical to process_data.py."""
    all_families = set()
    for families in GENRE_DEFINITIONS.values():
        all_families.update(families.keys())
    all_families = sorted(all_families)
    
    family_to_genres = {f: {} for f in all_families}
    for genre, families in GENRE_DEFINITIONS.items():
        for fam, weight in families.items():
            family_to_genres[fam][genre] = weight
    
    rows = []
    for g in unique_genres:
        vec = {"genre": g}
        for fam in all_families:
            vec[f"genre_{fam}"] = 0.0
        
        if g in GENRE_DEFINITIONS:
            for fam, w in GENRE_DEFINITIONS[g].items():
                vec[f"genre_{fam}"] = max(vec[f"genre_{fam}"], w)
                
        if g in GENRE_DEFINITIONS:
            SMEARING_DECAY = 0.5
            for fam_shared, w_g_in_shared in GENRE_DEFINITIONS[g].items():
                for neighbor, w_n_in_shared in family_to_genres[fam_shared].items():
                    if neighbor == g:
                        continue
                    connection_strength = w_g_in_shared * w_n_in_shared
                    if neighbor in GENRE_DEFINITIONS:
                        for fam_target, w_n_in_target in GENRE_DEFINITIONS[neighbor].items():
                            score = connection_strength * w_n_in_target * SMEARING_DECAY
                            col = f"genre_{fam_target}"
                            vec[col] = max(vec[col], score)
        
        rows.append(vec)
    
    df_emb = pl.from_dicts(rows)
    
    # L2 normalize
    genre_cols = [c for c in df_emb.columns if c.startswith("genre_")]
    emb_matrix = df_emb.select(genre_cols).to_numpy()
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    emb_matrix = emb_matrix / norms
    
    df_emb = df_emb.select("genre").hstack(
        pl.from_numpy(emb_matrix, schema=genre_cols)
    )
    
    return df_emb


def minmax_scale_with_params(
    df: pl.DataFrame,
    columns: list[str],
    params: dict[str, tuple[float, float]],
) -> pl.DataFrame:
    """Apply min-max scaling using stored parameters.
    
    Uses pre-computed min/max from the full pipeline to ensure
    incremental updates are scaled consistently with existing data.
    
    Formula: (value - min) / (max - min)
    Edge case: if max == min, set scaled value to 0.0
    """
    scale_exprs = []
    for col in columns:
        if col not in params:
            continue
        min_val, max_val = params[col]
        range_val = max_val - min_val
        if range_val == 0:
            scaled = pl.lit(0.0).alias(col)
        else:
            scaled = (
                (pl.col(col) - min_val) / range_val
            ).fill_nan(0.0).fill_null(0.0).alias(col)
        scale_exprs.append(scaled)
    
    return df.with_columns(scale_exprs)


def process_incremental_polars(
    new_tracks: pl.DataFrame,
    existing_ids_df: pl.DataFrame,
    max_songs: int,
    smear_strength: float,
    verbose: bool,
) -> pl.DataFrame:
    """Process new tracks through the pipeline - Pure Polars implementation."""
    
    # Load scaler params from manifest (required for consistent scaling)
    scaler_params = load_scaler_params()
    if scaler_params is None:
        raise ValueError(
            "Scaler parameters not found in manifest. "
            "Run the full pipeline first: python pipeline/process_data.py"
        )
    
    # Filter out tracks that already exist using Polars anti-join (memory efficient)
    original_count = len(new_tracks)
    new_tracks = new_tracks.join(existing_ids_df, on="track_id", how="anti")
    
    if len(new_tracks) == 0:
        print("  No new tracks to add (all already exist)")
        return pl.DataFrame()
    
    if verbose:
        print(f"  {original_count - len(new_tracks):,} duplicates filtered, {len(new_tracks):,} new tracks")
    
    df = new_tracks
    
    # Numeric columns to scale
    num_cols = [
        "year", "key", "popularity", "acousticness", "danceability", "duration_ms",
        "energy", "instrumentalness", "liveness", "loudness", "speechiness", "tempo",
        "valence", "time_signature"
    ]
    num_cols = [c for c in num_cols if c in df.columns]
    
    if num_cols:
        # Fill NaNs
        fill_exprs = []
        if "year" in df.columns:
            fill_exprs.append(pl.col("year").fill_null(2020))
        if "popularity" in df.columns:
            fill_exprs.append(pl.col("popularity").fill_null(25))
        
        if fill_exprs:
            df = df.with_columns(fill_exprs)
        
        # Fill remaining nulls with column means
        for col in num_cols:
            if col not in ["year", "popularity"]:
                mean_val = df[col].mean()
                df = df.with_columns(pl.col(col).fill_null(mean_val))
        
        # Scale using stored parameters for consistency with existing data
        # Clip to [0, 1] since new tracks may fall outside historic min/max
        df = minmax_scale_with_params(df, num_cols, scaler_params)
        df = df.with_columns([
            pl.col(c).clip(0.0, 1.0).cast(pl.Float32) for c in num_cols
        ])
    
    # Cap songs per artist using window function
    if 'artist_name' in df.columns and 'popularity' in df.columns:
        df = (
            df
            .sort("popularity", descending=True)
            .with_columns(
                pl.col("popularity")
                .rank("ordinal", descending=True)
                .over("artist_name")
                .alias("_rank")
            )
            .filter(pl.col("_rank") <= max_songs)
            .drop("_rank")
        )
        if verbose:
            print(f"  Capped to {max_songs} songs per artist: {len(df):,} tracks")
    
    # Process genre embeddings
    genre_cols = []
    if "genre" in df.columns:
        unique_genres = df["genre"].drop_nulls().unique().to_list()
        embedding_df = compute_genre_embeddings_polars(unique_genres)
        
        df = df.join(embedding_df, on="genre", how="left")
        
        genre_cols = [c for c in embedding_df.columns if c.startswith("genre_")]
        df = df.with_columns([
            pl.col(c).fill_null(0.0).cast(pl.Float32) for c in genre_cols
        ])
        
        # Apply inter-artist smearing
        if smear_strength > 0 and len(genre_cols) > 0:
            ag_counts = (
                df
                .group_by(["artist_name", "genre"])
                .len()
                .filter(pl.col("len") >= 1)
            )
            
            ag_with_vectors = ag_counts.join(embedding_df, on="genre", how="left")
            artist_identities = (
                ag_with_vectors
                .group_by("artist_name")
                .agg([pl.col(c).mean() for c in genre_cols])
            )
            
            profile_cols = [f"_profile_{c}" for c in genre_cols]
            artist_identities = artist_identities.rename({
                c: f"_profile_{c}" for c in genre_cols
            })
            
            df = df.join(artist_identities, on="artist_name", how="left")
            
            for p_col, g_col in zip(profile_cols, genre_cols):
                df = df.with_columns(
                    pl.when(pl.col(p_col).is_null())
                    .then(pl.col(g_col))
                    .otherwise(pl.col(p_col))
                    .alias(p_col)
                )
            
            blend_exprs = []
            for g_col, p_col in zip(genre_cols, profile_cols):
                blended = (
                    (1.0 - smear_strength) * pl.col(g_col) + 
                    smear_strength * pl.col(p_col)
                ).alias(g_col)
                blend_exprs.append(blended)
            
            df = df.with_columns(blend_exprs).drop(profile_cols)
            
            # Re-normalize
            genre_matrix = df.select(genre_cols).to_numpy()
            norms = np.linalg.norm(genre_matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            genre_matrix = genre_matrix / norms
            
            df = df.drop(genre_cols).hstack(
                pl.from_numpy(genre_matrix, schema=genre_cols)
            )
            df = df.with_columns([pl.col(c).cast(pl.Float32) for c in genre_cols])
    
    # Deduplicate tracks (handles variants like "Song" vs "Song - Remastered")
    n_before_dedup = len(df)
    df = deduplicate_tracks_polars(df)
    if verbose and n_before_dedup > len(df):
        print(f"  Deduplicated: {n_before_dedup - len(df):,} variant tracks removed")
    
    # Select final columns
    meta_cols = ["artist_name", "track_name", "track_id", "genre"]
    feature_cols = [
        "popularity", "year", "duration_ms",
        "acousticness", "danceability", "energy", "instrumentalness",
        "liveness", "loudness", "speechiness", "tempo", "valence"
    ]
    
    final_cols = meta_cols + [c for c in feature_cols if c in df.columns] + genre_cols
    final_cols = [c for c in final_cols if c in df.columns]
    df = df.select(final_cols)
    
    # Cast floats for memory efficiency
    float_cols = [c for c in df.columns if df[c].dtype in [pl.Float32, pl.Float64]]
    df = df.with_columns([pl.col(c).cast(pl.Float32) for c in float_cols])
    
    return df


def incremental_update(
    source_path: Path,
    target_path: Path,
    max_songs: int = 50,
    smear_strength: float = 0.6,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Append new tracks to encoded dataset."""
    
    if not target_path.exists():
        raise FileNotFoundError(
            f"Target dataset not found: {target_path}\n"
            "Run the full pipeline first: python pipeline/process_data.py"
        )
    
    # Load source
    print(f"Loading source: {source_path}")
    source_df = read_input_file(source_path, normalize_schema=True)
    
    if len(source_df) == 0:
        print("Source file is empty, nothing to append")
        return {'added': 0, 'total': 0}
    
    if verbose:
        print(f"  Source has {len(source_df):,} tracks")
    
    # Get existing track IDs (memory efficient - read just that column as DataFrame for anti-join)
    print(f"Loading existing track IDs from: {target_path}")
    existing_ids_df = pl.read_parquet(target_path, columns=["track_id"])
    existing_count = len(existing_ids_df)
    
    if verbose:
        print(f"  Existing dataset has {existing_count:,} tracks")
    
    # Process new tracks
    print("Processing new tracks...")
    processed_df = process_incremental_polars(
        source_df,
        existing_ids_df,
        max_songs,
        smear_strength,
        verbose,
    )
    
    del existing_ids_df
    
    del source_df
    
    if len(processed_df) == 0:
        return {'added': 0, 'total': existing_count}
    
    stats = {
        'added': len(processed_df),
        'total': existing_count + len(processed_df),
    }
    
    if dry_run:
        print(f"\n[DRY RUN] Would add {stats['added']:,} tracks")
        print(f"  New artists: {processed_df['artist_name'].n_unique():,}")
        if verbose:
            print(f"  Sample:\n{processed_df.head(5)}")
        return stats
    
    # Load existing and append
    print("Loading existing data for append...")
    existing_df = read_parquet_safe(target_path)
    
    if verbose:
        print(f"  Existing: {len(existing_df):,} tracks, {existing_df.estimated_size() / 1024 / 1024:.1f} MB")
    
    combined_df = pl.concat([existing_df, processed_df], how="diagonal")
    
    del existing_df
    del processed_df
    
    if verbose:
        print(f"  Combined: {len(combined_df):,} tracks, {combined_df.estimated_size() / 1024 / 1024:.1f} MB")
    
    # Atomic write
    print(f"Writing updated dataset...")
    atomic_write_parquet(
        combined_df,
        target_path,
        validate=validate_encoded_dataset,
        verbose=verbose,
    )
    
    update_manifest(
        operation="incremental_update",
        track_count=len(combined_df),
        artist_count=combined_df['artist_name'].n_unique(),
        extra={'tracks_added': stats['added']},
    )
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Append new tracks to encoded dataset (Pure Polars, low-memory)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source", type=Path, default=None,
        help="Source file with new tracks (default: auto-detect added_artists)",
    )
    parser.add_argument(
        "--target", type=Path, default=None,
        help="Target encoded dataset (default: data_encoded.parquet)",
    )
    parser.add_argument(
        "--max-songs", type=int, default=50,
        help="Maximum songs per artist",
    )
    parser.add_argument(
        "--smear-strength", type=float, default=0.6,
        help="Genre smearing strength (0.0 to 1.0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be added without writing",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()
    
    try:
        source_path = args.source or get_added_artists()
        if source_path is None:
            print("Error: No source file found. Specify --source or create added_artists.parquet")
            sys.exit(1)
        
        if not source_path.exists():
            print(f"Error: Source file not found: {source_path}")
            sys.exit(1)
        
        target_path = args.target or ENCODED_DATASET
        
        stats = incremental_update(
            source_path=source_path,
            target_path=target_path,
            max_songs=args.max_songs,
            smear_strength=args.smear_strength,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        
        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Incremental Update Complete:")
        print(f"  Added: {stats['added']:,} tracks")
        print(f"  Total: {stats['total']:,} tracks")
        
        if not args.dry_run and stats['added'] > 0:
            print(f"\n✓ Updated {target_path}")
            
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
