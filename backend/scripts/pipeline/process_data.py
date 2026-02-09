#!/usr/bin/env python3
"""
Process raw Spotify data into a cleaned, encoded parquet file.

Pure Polars implementation - optimized for 800MB RAM VPS.
No Pandas conversion = ~2-3x lower peak memory.

Usage:
    # Default paths from paths.py
    python process_data.py
    
    # Custom paths
    python process_data.py -i filtered.parquet -o encoded.parquet
    
    # With additional tracks to merge
    python process_data.py --merge added_artists.parquet

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
    FILTERED_CSV_ZIP,
    ENCODED_DATASET,
    get_filtered_dataset,
    get_added_artists,
)
from io_utils import (
    read_input_file,
    atomic_write_parquet,
    validate_encoded_dataset,
    update_manifest,
    save_scaler_params,
)
from genre_families import GENRE_DEFINITIONS
from track_dedup import deduplicate_tracks_polars


def compute_genre_embeddings_polars(unique_genres: list[str]) -> pl.DataFrame:
    """Compute dense embeddings for genres based on family relationships.
    
    Returns a Polars DataFrame with 'genre' column and 'genre_*' embedding columns.
    Uses NumPy only for L2 normalization of the small embedding matrix.
    """
    # Get all family dimensions from the definitions
    all_families = set()
    for families in GENRE_DEFINITIONS.values():
        all_families.update(families.keys())
    all_families = sorted(all_families)
    
    # Reverse mapping: Family -> {Genre: Weight}
    family_to_genres = {f: {} for f in all_families}
    for genre, families in GENRE_DEFINITIONS.items():
        for fam, weight in families.items():
            family_to_genres[fam][genre] = weight
    
    # Build embeddings as list of dicts (fast with Polars)
    rows = []
    for g in unique_genres:
        vec = {"genre": g}
        for fam in all_families:
            vec[f"genre_{fam}"] = 0.0
        
        # 1. Direct Membership
        if g in GENRE_DEFINITIONS:
            for fam, w in GENRE_DEFINITIONS[g].items():
                vec[f"genre_{fam}"] = max(vec[f"genre_{fam}"], w)
                
        # 2. Neighbor Connections: Propagate traits from neighbors sharing a family
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
    
    # Convert to Polars DataFrame
    df_emb = pl.from_dicts(rows)
    
    # L2 normalize embeddings (brief NumPy usage for this small matrix)
    genre_cols = [c for c in df_emb.columns if c.startswith("genre_")]
    emb_matrix = df_emb.select(genre_cols).to_numpy()
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    emb_matrix = emb_matrix / norms
    
    # Replace embedding columns with normalized values
    df_emb = df_emb.select("genre").hstack(
        pl.from_numpy(emb_matrix, schema=genre_cols)
    )
    
    return df_emb


def minmax_scale_polars(df: pl.LazyFrame, columns: list[str]) -> pl.LazyFrame:
    """Apply min-max scaling to columns using pure Polars expressions.
    
    Formula: (x - min) / (max - min)
    This replaces sklearn's MinMaxScaler without any Pandas conversion.
    """
    # Build expressions for each column
    scale_exprs = []
    for col in columns:
        # Use .over(pl.lit(True)) to compute global min/max (not per-group)
        scaled = (
            (pl.col(col) - pl.col(col).min()) / 
            (pl.col(col).max() - pl.col(col).min())
        ).fill_nan(0.0).fill_null(0.0).alias(col)
        scale_exprs.append(scaled)
    
    return df.with_columns(scale_exprs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process and encode Spotify song data (Pure Polars).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=None,
        help="Path to input file (parquet or csv). Default: auto from paths.py",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Path to output parquet file. Default: data_encoded.parquet",
    )
    parser.add_argument(
        "--merge",
        type=Path,
        default=None,
        help="Path to additional data to merge (e.g., added_artists.parquet)",
    )
    parser.add_argument(
        "--max-songs",
        type=int,
        default=50,
        help="Maximum songs per artist (keeps most popular)",
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
    return parser.parse_args()


def log(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg)


def load_and_merge_data(
    input_path: Path,
    merge_path: Path | None,
    verbose: bool,
) -> pl.LazyFrame:
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
    
    # Merge additional data if provided
    if merge_path and merge_path.exists():
        log(f"Merging additional data from {merge_path}...", verbose)
        df_merge = read_input_file(merge_path, normalize_schema=True)
        
        if "Unnamed: 0" in df_merge.columns:
            df_merge = df_merge.drop("Unnamed: 0")
        
        # Concatenate and deduplicate
        df = pl.concat([df, df_merge], how="diagonal")
        df = df.unique(subset=["track_id"], keep="first")
        log(f"After merge: {len(df):,} songs", verbose)
    
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
    input_path: Path,
    output_path: Path,
    merge_path: Path | None,
    max_songs: int,
    smear_strength: float,
    verbose: bool,
) -> None:
    """Main processing pipeline - Pure Polars implementation."""
    
    # Load data as LazyFrame
    lf, n_initial = load_and_merge_data(input_path, merge_path, verbose)
    
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
    
    # Fill remaining nulls with column means
    for col in num_cols:
        if col not in ["year", "popularity"]:
            mean_val = df[col].mean()
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
    log(f"Deduplicated tracks: {n_before_dedup - len(df):,} removed, {len(df):,} remaining", verbose)
    
    # Cap songs per artist using window function (Pure Polars)
    # This replaces: df.groupby("artist_name").cumcount() < max_songs
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
    
    removed = n_initial - len(df)
    log(f"Capped to {max_songs} songs per artist", verbose)
    log(f"Removed {removed:,} songs total, {len(df):,} remaining", verbose)

    # Core Metadata columns
    meta_cols = ["artist_name", "track_name", "track_id", "genre"]
    
    # Audio Features (Scaled 0-1)
    feature_cols = [
        "popularity", "year", "duration_ms",
        "acousticness", "danceability", "energy", "instrumentalness",
        "liveness", "loudness", "speechiness", "tempo", "valence"
    ]
    
    # Process genre embeddings
    genre_cols = []
    if "genre" in df.columns:
        log("Computing smart family embeddings...", verbose)
        unique_genres = df["genre"].drop_nulls().unique().to_list()
        
        # Compute embedding matrix (Pure Polars)
        embedding_df = compute_genre_embeddings_polars(unique_genres)
        
        # Join embeddings to main DataFrame
        df = df.join(embedding_df, on="genre", how="left")
        
        # Fill NaNs for genres with no families defined
        genre_cols = [c for c in embedding_df.columns if c.startswith("genre_")]
        df = df.with_columns([
            pl.col(c).fill_null(0.0).cast(pl.Float32) for c in genre_cols
        ])

        # Inter-artist smearing (Pure Polars)
        ARTIST_SMEAR_STRENGTH = smear_strength
        MIN_TRACKS_FOR_GENRE = 1
        TOP_GENRES = 0  # 0 = all
        
        if ARTIST_SMEAR_STRENGTH > 0:
            log(f"Applying inter-artist smearing (strength={ARTIST_SMEAR_STRENGTH})...", verbose)
            
            # Count (artist, genre) pairs and filter
            ag_counts = (
                df
                .group_by(["artist_name", "genre"])
                .len()
                .filter(pl.col("len") >= MIN_TRACKS_FOR_GENRE)
            )
            
            # Optionally limit to top N genres per artist
            if TOP_GENRES > 0:
                ag_counts = (
                    ag_counts
                    .sort("len", descending=True)
                    .with_columns(
                        pl.col("len").rank("ordinal", descending=True).over("artist_name").alias("_genre_rank")
                    )
                    .filter(pl.col("_genre_rank") <= TOP_GENRES)
                    .drop("_genre_rank")
                )
            
            # Get genre vectors and compute artist identity (mean of their genres)
            ag_with_vectors = ag_counts.join(embedding_df, on="genre", how="left")
            
            artist_identities = (
                ag_with_vectors
                .group_by("artist_name")
                .agg([pl.col(c).mean() for c in genre_cols])
            )
            
            # Rename to profile columns for the join
            profile_cols = [f"_profile_{c}" for c in genre_cols]
            artist_identities = artist_identities.rename({
                c: f"_profile_{c}" for c in genre_cols
            })
            
            # Join artist profiles to tracks
            df = df.join(artist_identities, on="artist_name", how="left")
            
            # Fallback: artists with no valid genres use their track's genre
            for p_col, g_col in zip(profile_cols, genre_cols):
                df = df.with_columns(
                    pl.when(pl.col(p_col).is_null())
                    .then(pl.col(g_col))
                    .otherwise(pl.col(p_col))
                    .alias(p_col)
                )
            
            # Blend: track = (1-strength)*track + strength*artist_profile
            blend_exprs = []
            for g_col, p_col in zip(genre_cols, profile_cols):
                blended = (
                    (1.0 - ARTIST_SMEAR_STRENGTH) * pl.col(g_col) + 
                    ARTIST_SMEAR_STRENGTH * pl.col(p_col)
                ).alias(g_col)
                blend_exprs.append(blended)
            
            df = df.with_columns(blend_exprs).drop(profile_cols)
            
            # Re-normalize for cosine similarity (brief NumPy usage)
            genre_matrix = df.select(genre_cols).to_numpy()
            norms = np.linalg.norm(genre_matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            genre_matrix = genre_matrix / norms
            
            # Replace genre columns with normalized values
            df = df.drop(genre_cols).hstack(
                pl.from_numpy(genre_matrix, schema=genre_cols)
            )
            
            # Cast back to Float32
            df = df.with_columns([pl.col(c).cast(pl.Float32) for c in genre_cols])

    # Select final columns
    final_cols = meta_cols + [c for c in feature_cols if c in df.columns] + genre_cols
    final_cols = [c for c in final_cols if c in df.columns]
    
    if not all(c in final_cols for c in meta_cols[:3]):  # artist, track, id
        print("Warning: Missing core columns.", file=sys.stderr)

    df = df.select(final_cols)
    log(f"Pruned columns. Keeping {len(genre_cols)} genre columns.", verbose)

    # Downcast floats to float16 for memory savings
    float_cols = [c for c in df.columns if df[c].dtype in [pl.Float32, pl.Float64]]
    df = df.with_columns([pl.col(c).cast(pl.Float32) for c in float_cols])
    
    if verbose:
        mem_mb = df.estimated_size() / (1024 * 1024)
        print(f"Memory usage (final): {mem_mb:.1f} MB")
        print("\nColumn types:")
        for dtype in df.dtypes:
            print(f"  {dtype}")

    # Atomic write with validation
    log(f"Writing to {output_path}...", verbose)
    atomic_write_parquet(
        df,
        output_path,
        compression="zstd",
        compression_level=20,
        validate=validate_encoded_dataset,
        verbose=verbose,
    )
    
    # Update manifest
    update_manifest(
        operation="full_process",
        track_count=len(df),
        artist_count=df["artist_name"].n_unique(),
    )

    # Summary
    print(f"\nProcessed {n_initial:,} -> {len(df):,} songs")
    print(f"Artists: {df['artist_name'].n_unique():,}")
    print(f"Output: {output_path}")


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
    
    # Resolve output path
    output_path = args.output or ENCODED_DATASET
    
    # Resolve merge path (auto-detect if not specified)
    merge_path = args.merge
    if merge_path is None:
        merge_path = get_added_artists()
        if merge_path:
            print(f"Auto-detected added_artists: {merge_path}")
    
    process_data(
        input_path=input_path,
        output_path=output_path,
        merge_path=merge_path,
        max_songs=args.max_songs,
        smear_strength=args.smear_strength,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
