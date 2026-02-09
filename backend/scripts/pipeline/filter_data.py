#!/usr/bin/env python3
"""
Filter raw Spotify data to remove unwanted content before processing.

Uses Polars for memory-efficient processing on VPS (800MB RAM limit).
Supports both Parquet (preferred) and legacy CSV input.

Usage:
    # Default: use paths from paths.py
    python filter_data.py
    
    # Custom input/output
    python filter_data.py -i data.parquet -o data_filtered.parquet
    
    # Legacy CSV support (auto-detected)
    python filter_data.py -i data.csv.zip -o data_filtered.parquet
"""

import argparse
import re
import sys
from pathlib import Path

import polars as pl

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from paths import (
    DATA_DIR, 
    get_input_dataset, 
    FILTERED_DATASET,
    FILTERED_CSV_ZIP,
)
from io_utils import (
    read_input_file, 
    atomic_write_parquet,
    validate_filtered_dataset,
)
from artist_reassignments import get_reassigned_artists, get_artist_genre

# Artists to exclude entirely (not reassign)
EXCLUDED_ARTISTS: set[str] = set()

# Genres to exclude entirely
EXCLUDED_GENRES = {
    'comedy',   # Spoken word, not music
}

# Pattern for detecting remixes
REMIX_PATTERN = re.compile(r'\bremix\b', re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter raw Spotify data before processing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=None,
        help="Path to input file (parquet or csv.zip). Default: auto-detect from paths.py",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Path to output parquet file. Default: data_filtered.parquet",
    )
    parser.add_argument(
        "--keep-remixes",
        action="store_true",
        default=False,
        help="Keep remix tracks (by default they are removed)",
    )
    parser.add_argument(
        "--min-songs",
        type=int,
        default=1,
        help="Minimum songs an artist must have to be included",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be filtered without writing output",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed filtering info",
    )
    return parser.parse_args()


def filter_data(
    input_path: Path,
    output_path: Path,
    keep_remixes: bool = False,
    min_songs: int = 1,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Filter dataset using Polars for memory efficiency.
    
    Returns stats dictionary with filtering summary.
    """
    
    print(f"Loading {input_path}...")
    df = read_input_file(input_path)
    original_count = len(df)
    original_artists = df['artist_name'].n_unique() if 'artist_name' in df.columns else 0
    
    if verbose:
        mem_mb = df.estimated_size() / (1024 * 1024)
        print(f"  Loaded {original_count:,} rows ({mem_mb:.1f} MB in memory)")
    
    stats = {
        'original_tracks': original_count,
        'original_artists': original_artists,
        'removed': {},
    }
    
    # Filter 0: Remove rows with null required fields (data quality - first!)
    required_fields = ["artist_name", "track_name", "track_id"]
    null_removed = 0
    for field in required_fields:
        if field in df.columns:
            null_count = df[field].null_count()
            if null_count > 0:
                df = df.filter(pl.col(field).is_not_null())
                null_removed += null_count
                if verbose:
                    print(f"  Null {field}: {null_count:,} rows removed")
    stats['removed']['null_required_fields'] = null_removed
    
    # Get reassigned artists for genre updates
    reassigned = get_reassigned_artists()
    effective_exclusions = EXCLUDED_ARTISTS - reassigned
    
    # Build filter expressions using Polars
    filters = []
    
    # Filter 1: Excluded artists (but not those with reassignments)
    if 'artist_name' in df.columns and effective_exclusions:
        excluded_mask = df['artist_name'].is_in(list(effective_exclusions))
        stats['removed']['excluded_artists'] = excluded_mask.sum()
        if verbose and stats['removed']['excluded_artists'] > 0:
            print(f"  Excluded artists: {stats['removed']['excluded_artists']:,} tracks")
        filters.append(~excluded_mask)
    else:
        stats['removed']['excluded_artists'] = 0
    
    # Filter 2: Excluded genres
    if 'genre' in df.columns:
        genre_mask = df['genre'].is_in(list(EXCLUDED_GENRES))
        stats['removed']['excluded_genres'] = genre_mask.sum()
        if verbose and stats['removed']['excluded_genres'] > 0:
            for g in EXCLUDED_GENRES:
                count = (df['genre'] == g).sum()
                if count > 0:
                    print(f"  Genre '{g}': {count:,} tracks")
        filters.append(~genre_mask)
    else:
        stats['removed']['excluded_genres'] = 0
    
    # Filter 3: Remixes (unless --keep-remixes)
    if not keep_remixes and 'track_name' in df.columns:
        # Polars regex filter - case insensitive
        remix_mask = df['track_name'].cast(pl.Utf8).str.to_lowercase().str.contains(r'\bremix\b')
        stats['removed']['remixes'] = remix_mask.sum()
        if verbose:
            print(f"  Remixes: {stats['removed']['remixes']:,} tracks")
        filters.append(~remix_mask)
    else:
        stats['removed']['remixes'] = 0
    
    # Apply all content filters at once
    if filters:
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f
        df = df.filter(combined_filter)
    
    # Apply genre reassignments AFTER content filtering
    if reassigned and 'genre' in df.columns and 'artist_name' in df.columns:
        reassign_mask = df['artist_name'].is_in(list(reassigned))
        n_reassigned = reassign_mask.sum()
        
        if n_reassigned > 0:
            # Get the new genres for reassigned artists
            # We need to do this row by row since get_artist_genre is a lookup
            artist_to_genre = {a: get_artist_genre(a) for a in reassigned}
            
            # Use when/then/otherwise for conditional update
            df = df.with_columns(
                pl.when(pl.col('artist_name').is_in(list(reassigned)))
                .then(pl.col('artist_name').replace(artist_to_genre))
                .otherwise(pl.col('genre'))
                .alias('genre')
            )
            
            if verbose:
                print(f"  Reassigned genres for {n_reassigned:,} tracks")
    
    # Filter 4: Minimum songs per artist
    if min_songs > 1 and 'artist_name' in df.columns:
        before_min = len(df)
        
        # Count tracks per artist
        artist_counts = df.group_by('artist_name').agg(pl.len().alias('_count'))
        keep_artists = artist_counts.filter(pl.col('_count') >= min_songs)['artist_name']
        
        df = df.filter(pl.col('artist_name').is_in(keep_artists))
        stats['removed']['min_songs'] = before_min - len(df)
        
        if verbose:
            removed_artists = len(artist_counts) - len(keep_artists)
            print(f"  Artists with < {min_songs} songs: {removed_artists:,} artists removed")
    else:
        stats['removed']['min_songs'] = 0
    
    stats['final_tracks'] = len(df)
    stats['final_artists'] = df['artist_name'].n_unique() if 'artist_name' in df.columns else 0
    stats['total_removed'] = original_count - len(df)
    
    if not dry_run:
        print(f"Saving to {output_path}...")
        atomic_write_parquet(
            df, 
            output_path, 
            validate=validate_filtered_dataset,
            verbose=verbose,
        )
    
    return stats


def main() -> None:
    args = parse_args()
    
    # Resolve input path
    if args.input:
        input_path = args.input
    else:
        try:
            input_path = get_input_dataset()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            print("Run convert_to_parquet.py first or specify --input", file=sys.stderr)
            sys.exit(1)
    
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    # Resolve output path
    output_path = args.output or FILTERED_DATASET
    
    stats = filter_data(
        input_path=input_path,
        output_path=output_path,
        keep_remixes=args.keep_remixes,
        min_songs=args.min_songs,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Filtering Summary:")
    print(f"  Original: {stats['original_tracks']:,} tracks, {stats['original_artists']:,} artists")
    print(f"  Removed:")
    print(f"    - Excluded artists: {stats['removed']['excluded_artists']:,}")
    print(f"    - Excluded genres:  {stats['removed']['excluded_genres']:,}")
    print(f"    - Remixes:          {stats['removed']['remixes']:,}")
    print(f"    - Min songs filter: {stats['removed']['min_songs']:,}")
    print(f"    - Total:            {stats['total_removed']:,}")
    print(f"  Final: {stats['final_tracks']:,} tracks, {stats['final_artists']:,} artists")
    
    if not args.dry_run:
        print(f"\nOutput: {output_path}")
        print(f"Next: python process_data.py -i {output_path}")


if __name__ == "__main__":
    main()
