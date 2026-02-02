#!/usr/bin/env python3
"""
Process raw Spotify data into a cleaned, encoded parquet file.

Usage:
    python process_data.py                          # Use all defaults
    python process_data.py --max-songs 100          # Limit to 100 songs per artist
    python process_data.py -i raw.csv -o out.parquet --min-songs 5
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sklearn.preprocessing import MinMaxScaler
import numpy as np
# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

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
        default=Path("data_filtered.csv.zip"),
        help="Path to input CSV file (use filter_data.py first)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("../data/data_encoded.parquet"),
        help="Path to output parquet file",
    )
    parser.add_argument(
        "--merge",
        type=Path,
        default=None,
        help="Path to additional CSV to merge (e.g., added_artists.csv.zip)",
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


def process_data(
    input_path: Path,
    output_path: Path,
    merge_path: Path,
    max_songs: int,
    smear_strength: float,
    verbose: bool,
) -> None:
    """Main processing pipeline."""
    
    # Load data
    log(f"Loading data from {input_path}...", verbose)
    df = pd.read_csv(input_path, low_memory=False)
    
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])
    
    # Merge additional data if provided
    if merge_path and merge_path.exists():
        log(f"Merging additional data from {merge_path}...", verbose)
        df_merge = pd.read_csv(merge_path, low_memory=False)
        if "Unnamed: 0" in df_merge.columns:
            df_merge = df_merge.drop(columns=["Unnamed: 0"])
        df = pd.concat([df, df_merge], ignore_index=True)
        df = df.drop_duplicates(subset=["track_id"], keep="first")
        log(f"After merge: {len(df):,} songs", verbose)
    
    n_initial = len(df)
    log(f"Loaded {n_initial:,} songs", verbose)
    log(f"Memory usage (before): {df.memory_usage(index=True).sum():,} bytes", verbose)

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
            artist_identities = valid_ag_vectors.groupby("artist_name")[genre_cols].mean()
            
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
    
    # Use float16 for audio features
    float_cols = df.select_dtypes("floating").columns
    for c in float_cols:
        df[c] = df[c].astype("float16")
        
    log(f"Memory usage (after optimization): {df.memory_usage(index=True).sum():,} bytes", verbose)
    if verbose:
        print("\nFinal Data Types:")
        print(df.dtypes.value_counts())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Use max compression (zstd level 22) and byte stream split for floats
    df.to_parquet(
        output_path,
        engine="pyarrow",
        compression="zstd",
        compression_level=22,
        index=False,
        use_byte_stream_split=True,
    )
    log(f"Saved to {output_path}", verbose)

    # Summary
    print(f"Processed {n_initial:,} -> {len(df):,} songs")
    print(f"Artists: {df['artist_name'].nunique():,}")
    print(f"Output: {output_path}")


def main() -> None:
    args = parse_args()
    
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    
    process_data(
        input_path=args.input,
        output_path=args.output,
        merge_path=args.merge,
        max_songs=args.max_songs,
        smear_strength=args.smear_strength,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()