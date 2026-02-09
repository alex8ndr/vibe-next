#!/usr/bin/env python3
"""
Process raw Spotify data into a cleaned, encoded parquet file.

Uses Polars for memory-efficient I/O, Pandas for numpy-heavy computations.
Designed for 800MB VPS RAM constraint.

Usage:
    # Default paths from paths.py
    python process_data.py
    
    # Custom paths
    python process_data.py -i filtered.parquet -o encoded.parquet
    
    # With additional tracks to merge
    python process_data.py --merge added_artists.parquet
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from sklearn.preprocessing import MinMaxScaler

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
)
from genre_families import GENRE_DEFINITIONS
from track_dedup import deduplicate_tracks


def compute_genre_embeddings(unique_genres):
    """Compute dense embeddings for genres based on family relationships.
    
    Each genre is defined by its weighted memberships in multiple families.
    We also add "neighbor connections" - if two genres share a family, they
    influence each other's embeddings in other families.
    
    Returns: DataFrame indexed by genre, columns are family names (prefixed with 'genre_')
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
    
    embeddings = {}
    
    for g in unique_genres:
        # Initialize vector for this genre
        vec = {f"genre_{fam}": 0.0 for fam in all_families}
        
        # 1. Direct Membership
        if g in GENRE_DEFINITIONS:
            for fam, w in GENRE_DEFINITIONS[g].items():
                vec[f"genre_{fam}"] = max(vec[f"genre_{fam}"], w)
                
        # 2. Neighbor Connections: Propagate traits from neighbors sharing a family
        if g in GENRE_DEFINITIONS:
            for fam_shared, w_g_in_shared in GENRE_DEFINITIONS[g].items():
                # Look at other members of this shared family
                # Decay neighbor influence (50%) to prevent generic genres from over-absorbing traits
                SMEARING_DECAY = 0.5
                
                for neighbor, w_n_in_shared in family_to_genres[fam_shared].items():
                    if neighbor == g:
                        continue
                        
                    # Connection strength based on shared family
                    connection_strength = w_g_in_shared * w_n_in_shared
                    
                    # Propagate neighbor's families to g (with decay)
                    if neighbor in GENRE_DEFINITIONS:
                        for fam_target, w_n_in_target in GENRE_DEFINITIONS[neighbor].items():
                            score = connection_strength * w_n_in_target * SMEARING_DECAY
                            col = f"genre_{fam_target}"
                            vec[col] = max(vec[col], score)
                            
        embeddings[g] = vec

    # L2 normalize embeddings to keep direction but remove magnitude bias
    df_emb = pd.DataFrame.from_dict(embeddings, orient='index')
    norms = np.linalg.norm(df_emb.values, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    df_emb[:] = df_emb.values / norms
    
    return df_emb


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process and encode Spotify song data.",
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
) -> pd.DataFrame:
    """
    Load data using Polars (memory efficient), convert to Pandas for processing.
    
    Why Polars for I/O:
    - 2-3x more memory-efficient parquet reading vs Pandas
    - Better at handling large files on 800MB RAM VPS
    - Streaming reads possible (though not used here for stability)
    
    Why Pandas for processing:
    - sklearn's MinMaxScaler requires numpy arrays
    - groupby().apply() with custom functions is more natural
    - The conversion happens ONCE at the end of I/O, not per-operation
    
    Memory optimization note:
    - We could keep data in Polars longer and extract numpy arrays only for
      sklearn operations, but the current approach is simpler and the memory
      peak is still acceptable (~500MB for 1M tracks)
    - Future optimization: use Polars native operations for everything except
      sklearn, then extract only the columns needed for scaling
    """
    log(f"Loading data from {input_path}...", verbose)
    
    # Read with Polars (memory efficient), normalize schema for consistent types
    df_pl = read_input_file(input_path, normalize_schema=True)
    
    # Remove index column if present (legacy from Pandas CSV export)
    if "Unnamed: 0" in df_pl.columns:
        df_pl = df_pl.drop("Unnamed: 0")
    
    # Merge additional data if provided
    if merge_path and merge_path.exists():
        log(f"Merging additional data from {merge_path}...", verbose)
        
        # Read and normalize schema - this ensures both DataFrames have 
        # matching types, avoiding the need for ad-hoc casting at merge time
        df_merge = read_input_file(merge_path, normalize_schema=True)
        
        if "Unnamed: 0" in df_merge.columns:
            df_merge = df_merge.drop("Unnamed: 0")
        
        # Both DataFrames now have canonical types from schema.py
        # Concatenate (diagonal handles missing columns) and deduplicate by track_id
        df_pl = pl.concat([df_pl, df_merge], how="diagonal")
        df_pl = df_pl.unique(subset=["track_id"], keep="first")
        log(f"After merge: {len(df_pl):,} songs", verbose)
    
    n_initial = len(df_pl)
    log(f"Loaded {n_initial:,} songs", verbose)
    
    if verbose:
        mem_mb = df_pl.estimated_size() / (1024 * 1024)
        print(f"  Polars memory: {mem_mb:.1f} MB")
    
    # Convert to Pandas for sklearn/numpy operations
    # This is the ONE conversion point - don't go back and forth
    df = df_pl.to_pandas()
    
    # Free Polars memory explicitly
    del df_pl
    
    if verbose:
        mem_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)
        print(f"  Pandas memory: {mem_mb:.1f} MB")
    
    return df


def process_data(
    input_path: Path,
    output_path: Path,
    merge_path: Path | None,
    max_songs: int,
    smear_strength: float,
    verbose: bool,
) -> None:
    """Main processing pipeline."""
    
    # Load data (Polars read -> Pandas for processing)
    df = load_and_merge_data(input_path, merge_path, verbose)
    n_initial = len(df)

    # Scale numeric columns
    num_cols = [
        "year", "key", "popularity", "acousticness", "danceability", "duration_ms",
        "energy", "instrumentalness", "liveness", "loudness", "speechiness", "tempo",
        "valence", "time_signature"
    ]
    num_cols = [c for c in num_cols if c in df.columns]
    
    if num_cols:
        log(f"Scaling {len(num_cols)} numeric columns", verbose)
        
        # Fill NaNs before scaling
        if "year" in df.columns:
             df["year"] = df["year"].fillna(2020)
        if "popularity" in df.columns:
             df["popularity"] = df["popularity"].fillna(25)
             
        # Fill any remaining NaNs (audio features) with mean
        df[num_cols] = df[num_cols].fillna(df[num_cols].mean())
        
        scaler = MinMaxScaler()
        df[num_cols] = scaler.fit_transform(df[num_cols]).astype("float32")
    # Convert string columns to categorical
    for col in df.select_dtypes("object").columns:
        if col in ["artist_name", "album_name", "track_name"]:
            df[col] = df[col].astype("category")

    # Validate required columns
    if "artist_name" not in df.columns or "popularity" not in df.columns:
        print("Error: Required columns 'artist_name' and 'popularity' are missing.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate tracks per artist (normalize case, prefer originals over variants)
    n_before_dedup = len(df)
    df = deduplicate_tracks(df, track_col="track_name", artist_col="artist_name")
    log(f"Deduplicated tracks: {n_before_dedup - len(df):,} removed, {len(df):,} remaining", verbose)
    
    # Cap songs per artist (keep most popular) - vectorized rank approach
    df = df.sort_values("popularity", ascending=False)
    df["_rank"] = df.groupby("artist_name", observed=True).cumcount()
    df = df[df["_rank"] < max_songs].drop(columns=["_rank"])
    
    removed = n_initial - len(df)
    log(f"Capped to {max_songs} songs per artist", verbose)
    log(f"Removed {removed:,} songs total, {len(df):,} remaining", verbose)

    # Core Metadata (including original genre for display)
    meta_cols = ["artist_name", "track_name", "track_id", "genre"]
    
    # Audio Features (Scaled 0-1)
    feature_cols = [
        "popularity", "year", "duration_ms",
        "acousticness", "danceability", "energy", "instrumentalness",
        "liveness", "loudness", "speechiness", "tempo", "valence"
    ]
    
    # Process genre column if present
    genre_cols = []
    if "genre" in df.columns:
        log("Computing smart family embeddings...", verbose)
        unique_genres = df["genre"].dropna().unique()
        
        # Compute embedding matrix (Genres x Families)
        embedding_df = compute_genre_embeddings(unique_genres)
        
        # Merge embeddings (replaces legacy OHE + Smearing)
        df = df.merge(embedding_df, left_on="genre", right_index=True, how="left")
        
        # Clean up: fill NaNs (for genres with no families defined) with 0
        new_cols = embedding_df.columns.tolist()
        df[new_cols] = df[new_cols].fillna(0).astype("float32")
        
        genre_cols = new_cols

        # Inter-artist smearing: blend track genre with artist's overall genre profile
        # Runs AFTER cross-genre smearing so artist identity uses smeared vectors
        
        # Config
        ARTIST_SMEAR_STRENGTH = smear_strength  # 0 = disabled
        MIN_TRACKS_FOR_GENRE = 1  # min tracks in genre to count toward identity
        TOP_GENRES = 0            # 0 = all, N = only top N genres per artist
        
        if ARTIST_SMEAR_STRENGTH > 0:
            log(f"Applying inter-artist smearing (strength={ARTIST_SMEAR_STRENGTH}, min_tracks={MIN_TRACKS_FOR_GENRE}, top_genres={TOP_GENRES or 'all'})...", verbose)
            
            # Count (artist, genre) pairs
            ag_counts = df.groupby(["artist_name", "genre"], observed=True).size()
            valid_ag = ag_counts[ag_counts >= MIN_TRACKS_FOR_GENRE].reset_index(name="count")[["artist_name", "genre", "count"]]
            
            # Optionally limit to top N genres per artist
            if TOP_GENRES > 0:
                valid_ag = valid_ag.sort_values("count", ascending=False)
                valid_ag = valid_ag.groupby("artist_name", observed=True).head(TOP_GENRES)
            
            # Get genre vectors and compute artist identity (mean of their genres)
            valid_ag_vectors = valid_ag.merge(embedding_df, left_on="genre", right_index=True)
            artist_identities = valid_ag_vectors.groupby("artist_name", observed=True)[genre_cols].mean()
            
            # Merge and blend
            profile_cols = [f"_profile_{c}" for c in genre_cols]
            artist_identities.columns = profile_cols
            df = df.merge(artist_identities, on="artist_name", how="left")
            
            # Fallback: artists with no valid genres use their track's genre
            for p_col, g_col in zip(profile_cols, genre_cols):
                df[p_col] = df[p_col].fillna(df[g_col])
            
            # Blend: track = (1-strength)*track + strength*artist_profile
            for g_col, p_col in zip(genre_cols, profile_cols):
                df[g_col] = (1.0 - ARTIST_SMEAR_STRENGTH) * df[g_col] + ARTIST_SMEAR_STRENGTH * df[p_col]
            
            df = df.drop(columns=profile_cols)
            
            # Re-normalize for cosine similarity
            norms = np.linalg.norm(df[genre_cols].values, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            df[genre_cols] = df[genre_cols] / norms


    final_cols = meta_cols + [c for c in feature_cols if c in df.columns] + genre_cols
    
    # Only keep columns that actually exist
    final_cols = [c for c in final_cols if c in df.columns]
    
    # Check for missing functional columns
    if not all(c in final_cols for c in meta_cols):
        print("Warning: Missing core columns (artist/track/id). App implementation relies on these being present.", file=sys.stderr)

    df = df[final_cols].copy()
    log(f"Pruned columns. Keeping {len(genre_cols)} genre columns.", verbose)

    # Downcast integers
    for col in df.select_dtypes("integer").columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    
    # Use float16 for audio features (saves ~50% memory)
    float_cols = df.select_dtypes("floating").columns
    for c in float_cols:
        df[c] = df[c].astype("float16")
        
    if verbose:
        mem_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)
        print(f"Memory usage (after optimization): {mem_mb:.1f} MB")
        print("\nFinal Data Types:")
        print(df.dtypes.value_counts())

    # Convert back to Polars for efficient parquet writing
    log("Converting to Polars for output...", verbose)
    df_pl = pl.from_pandas(df)
    
    # Free Pandas memory
    del df
    
    # Atomic write with validation
    log(f"Writing to {output_path}...", verbose)
    atomic_write_parquet(
        df_pl,
        output_path,
        compression="zstd",
        compression_level=12,  # Good balance of speed vs size
        validate=validate_encoded_dataset,
        verbose=verbose,
    )
    
    # Update manifest
    update_manifest(
        operation="full_process",
        track_count=len(df_pl),
        artist_count=df_pl['artist_name'].n_unique(),
    )

    # Summary
    print(f"\nProcessed {n_initial:,} -> {len(df_pl):,} songs")
    print(f"Artists: {df_pl['artist_name'].n_unique():,}")
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