#!/usr/bin/env python3
"""
Incremental update: Append new tracks to encoded dataset without full reprocessing.

This is the PREFERRED low-memory update strategy for VPS (~200-300MB peak RAM).
Use this for routine artist additions. Run full pipeline monthly to "rebase".

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
    
What this does:
    1. Reads only the new tracks file (small, ~1-10MB)
    2. Processes them through genre embeddings
    3. Appends directly to data_encoded.parquet
    4. Validates the result
    
What this does NOT do:
    - Does not re-filter the base dataset
    - Does not update existing tracks
    - Does not remove duplicates across base+new (handled at read time)
    
Memory: ~200-300MB regardless of base dataset size
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from sklearn.preprocessing import MinMaxScaler

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
)
from genre_families import GENRE_DEFINITIONS


def compute_genre_embeddings(unique_genres: list[str]) -> pd.DataFrame:
    """Compute dense embeddings for genres based on family relationships.
    
    Identical to process_data.py implementation for consistency.
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
        vec = {f"genre_{fam}": 0.0 for fam in all_families}
        
        # Direct Membership
        if g in GENRE_DEFINITIONS:
            for fam, w in GENRE_DEFINITIONS[g].items():
                vec[f"genre_{fam}"] = max(vec[f"genre_{fam}"], w)
                
        # Neighbor Connections (smearing)
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
                            
        embeddings[g] = vec

    # L2 normalize embeddings
    df_emb = pd.DataFrame.from_dict(embeddings, orient='index')
    norms = np.linalg.norm(df_emb.values, axis=1, keepdims=True)
    norms[norms == 0] = 1
    df_emb[:] = df_emb.values / norms
    
    return df_emb


def process_incremental(
    new_tracks: pl.DataFrame,
    existing_track_ids: set[str],
    max_songs: int,
    smear_strength: float,
    verbose: bool,
) -> pl.DataFrame:
    """Process new tracks through the same pipeline as process_data.py."""
    
    # Filter out tracks that already exist
    original_count = len(new_tracks)
    new_tracks = new_tracks.filter(~pl.col('track_id').is_in(list(existing_track_ids)))
    
    if len(new_tracks) == 0:
        print("  No new tracks to add (all already exist)")
        return pl.DataFrame()
    
    if verbose:
        print(f"  {original_count - len(new_tracks):,} duplicates filtered, {len(new_tracks):,} new tracks")
    
    # Convert to Pandas for processing (consistent with process_data.py)
    df = new_tracks.to_pandas()
    del new_tracks
    
    # Numeric columns to scale
    num_cols = [
        "year", "key", "popularity", "acousticness", "danceability", "duration_ms",
        "energy", "instrumentalness", "liveness", "loudness", "speechiness", "tempo",
        "valence", "time_signature"
    ]
    num_cols = [c for c in num_cols if c in df.columns]
    
    if num_cols:
        # Fill NaNs
        if "year" in df.columns:
            df["year"] = df["year"].fillna(2020)
        if "popularity" in df.columns:
            df["popularity"] = df["popularity"].fillna(25)
        df[num_cols] = df[num_cols].fillna(df[num_cols].mean())
        
        # Scale to 0-1 range
        scaler = MinMaxScaler()
        df[num_cols] = scaler.fit_transform(df[num_cols]).astype("float32")
    
    # Cap songs per artist
    if 'artist_name' in df.columns and 'popularity' in df.columns:
        df = df.sort_values("popularity", ascending=False)
        df["_rank"] = df.groupby("artist_name").cumcount()
        df = df[df["_rank"] < max_songs].drop(columns=["_rank"])
        if verbose:
            print(f"  Capped to {max_songs} songs per artist: {len(df):,} tracks")
    
    # Process genre embeddings
    genre_cols = []
    if "genre" in df.columns:
        unique_genres = df["genre"].dropna().unique()
        embedding_df = compute_genre_embeddings(list(unique_genres))
        
        df = df.merge(embedding_df, left_on="genre", right_index=True, how="left")
        
        new_cols = embedding_df.columns.tolist()
        df[new_cols] = df[new_cols].fillna(0).astype("float32")
        genre_cols = new_cols
        
        # Apply inter-artist smearing
        if smear_strength > 0 and len(genre_cols) > 0:
            ag_counts = df.groupby(["artist_name", "genre"]).size()
            valid_ag = ag_counts[ag_counts >= 1].reset_index(name="count")[["artist_name", "genre", "count"]]
            valid_ag_vectors = valid_ag.merge(embedding_df, left_on="genre", right_index=True)
            artist_identities = valid_ag_vectors.groupby("artist_name")[genre_cols].mean()
            
            profile_cols = [f"_profile_{c}" for c in genre_cols]
            artist_identities.columns = profile_cols
            df = df.merge(artist_identities, on="artist_name", how="left")
            
            for p_col, g_col in zip(profile_cols, genre_cols):
                df[p_col] = df[p_col].fillna(df[g_col])
            
            for g_col, p_col in zip(genre_cols, profile_cols):
                df[g_col] = (1.0 - smear_strength) * df[g_col] + smear_strength * df[p_col]
            
            df = df.drop(columns=profile_cols)
            
            # Re-normalize
            norms = np.linalg.norm(df[genre_cols].values, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            df[genre_cols] = df[genre_cols] / norms
    
    # Select final columns (same as process_data.py)
    meta_cols = ["artist_name", "track_name", "track_id", "genre"]
    feature_cols = [
        "popularity", "year", "duration_ms",
        "acousticness", "danceability", "energy", "instrumentalness",
        "liveness", "loudness", "speechiness", "tempo", "valence"
    ]
    
    final_cols = meta_cols + [c for c in feature_cols if c in df.columns] + genre_cols
    final_cols = [c for c in final_cols if c in df.columns]
    df = df[final_cols].copy()
    
    # Downcast for memory efficiency
    for col in df.select_dtypes("integer").columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    
    for c in df.select_dtypes("floating").columns:
        df[c] = df[c].astype("float16")
    
    # Convert back to Polars
    return pl.from_pandas(df)


def incremental_update(
    source_path: Path,
    target_path: Path,
    max_songs: int = 50,
    smear_strength: float = 0.6,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Append new tracks to encoded dataset.
    
    Returns stats dict with counts.
    """
    
    # Validate target exists
    if not target_path.exists():
        raise FileNotFoundError(
            f"Target dataset not found: {target_path}\n"
            "Run the full pipeline first: python pipeline/process_data.py"
        )
    
    # Load source (new tracks)
    print(f"Loading source: {source_path}")
    source_df = read_input_file(source_path)
    
    if len(source_df) == 0:
        print("Source file is empty, nothing to append")
        return {'added': 0, 'total': 0}
    
    if verbose:
        print(f"  Source has {len(source_df):,} tracks")
    
    # Get existing track IDs (read just that column for memory efficiency)
    print(f"Loading existing track IDs from: {target_path}")
    existing_df = pl.read_parquet(target_path, columns=["track_id"])
    existing_track_ids = set(existing_df["track_id"].to_list())
    existing_count = len(existing_track_ids)
    del existing_df
    
    if verbose:
        print(f"  Existing dataset has {existing_count:,} tracks")
    
    # Process new tracks
    print("Processing new tracks...")
    processed_df = process_incremental(
        source_df,
        existing_track_ids,
        max_songs,
        smear_strength,
        verbose,
    )
    
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
            print(f"  Sample: {processed_df.head(5)}")
        return stats
    
    # Load existing data and append
    print("Loading existing data for append...")
    existing_df = read_parquet_safe(target_path)
    
    if verbose:
        print(f"  Existing: {len(existing_df):,} tracks, {existing_df.estimated_size() / 1024 / 1024:.1f} MB")
    
    # Concatenate (diagonal handles column differences)
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
    
    # Update manifest
    update_manifest(
        operation="incremental_update",
        track_count=len(combined_df),
        artist_count=combined_df['artist_name'].n_unique(),
        extra={'tracks_added': stats['added']},
    )
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Append new tracks to encoded dataset (low-memory update)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Source file with new tracks (default: auto-detect added_artists)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Target encoded dataset (default: data_encoded.parquet)",
    )
    parser.add_argument(
        "--max-songs",
        type=int,
        default=50,
        help="Maximum songs per artist",
    )
    parser.add_argument(
        "--smear-strength",
        type=float,
        default=0.6,
        help="Genre smearing strength (0.0 to 1.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be added without writing",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    source_path = args.source or get_added_artists()
    if source_path is None:
        print("Error: No source file found. Specify --source or create added_artists.parquet")
        sys.exit(1)
    
    if not source_path.exists():
        print(f"Error: Source file not found: {source_path}")
        sys.exit(1)
    
    target_path = args.target or ENCODED_DATASET
    
    try:
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
