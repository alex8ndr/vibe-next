#!/usr/bin/env python3
"""
Filter raw Spotify data to remove unwanted content before processing.

Run this BEFORE process_data.py:
    python filter_data.py -i data.csv.zip -o data_filtered.csv.zip
    python process_data.py -i data_filtered.csv.zip

Or pipe directly (if not using zip output):
    python filter_data.py -i data.csv.zip -o data_filtered.csv
    python process_data.py -i data_filtered.csv
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

# Christian/CCM artists mislabeled in mainstream genres (rock, alt-rock, metal, etc.)
EXCLUDED_ARTISTS = {
    # Worship/CCM
    'Hillsong Worship', 'Hillsong United', 'Hillsong Young & Free', 'Bethel Music',
    'Casting Crowns', 'MercyMe', 'for KING & COUNTRY', 'Chris Tomlin', 'Lauren Daigle',
    'Newsboys', 'Third Day', 'TobyMac', 'DC Talk', 'Audio Adrenaline', 'Jars of Clay',
    'Building 429', 'Sidewalk Prophets', 'Matthew West', 'Zach Williams', 'We The Kingdom',
    'CAIN', 'Brandon Lake', 'Anne Wilson', 'I Am They', 'Danny Gokey', 'Tauren Wells',
    'Michael W. Smith', 'Amy Grant', 'Steven Curtis Chapman', 'Natalie Grant', 'Jeremy Camp',
    'Phil Wickham', 'Matt Redman', 'Kari Jobe', 'Passion', 'Crowder', 'Elevation Worship',
    'Jesus Culture', 'Maverick City Music', 'Vertical Worship', 'Worship Circle',
    
    # Christian Rock/Metal
    'Skillet', 'Switchfoot', 'Relient K', 'Thousand Foot Krutch', 'Kutless', 'Needtobreathe',
    'Hawk Nelson', 'Disciple', 'Flyleaf', 'Fireflight', 'Family Force 5', 'Demon Hunter',
    'Underoath', 'The Almost', 'House of Heroes', 'Emery', 'As I Lay Dying',
    'August Burns Red', 'The Devil Wears Prada', 'Oh Sleeper', 'Wolves at the Gate',
    'Fit For a King', 'Silent Planet', 'War of Ages', 'Living Sacrifice', 'Haste the Day',
    'P.O.D.', 'Pillar', 'Twelve Stones', 'Anberlin', 'The Classic Crime', 'Icon for Hire',
    'Lacey Sturm', 'Stryper', 'Petra', 'Red', 'Lecrae',
}

# Genres to exclude entirely
EXCLUDED_GENRES = {
    'gospel',   # Christian content
    'comedy',   # Spoken word, not music
}


REMIX_PATTERN = re.compile(r'\bremix\b', re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter raw Spotify data before processing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=Path("data.csv.zip"),
        help="Path to input CSV file",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("data_filtered.csv.zip"),
        help="Path to output CSV file",
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
        default=2,
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
    min_songs: int = 2,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Filter dataset and return stats."""
    
    print(f"Loading {input_path}...")
    df = pd.read_csv(input_path, low_memory=False)
    original_count = len(df)
    original_artists = df['artist_name'].nunique() if 'artist_name' in df.columns else 0
    
    stats = {
        'original_tracks': original_count,
        'original_artists': original_artists,
        'removed': {},
    }
    
    # Filter excluded artists
    if 'artist_name' in df.columns:
        artist_mask = df['artist_name'].isin(EXCLUDED_ARTISTS)
        stats['removed']['excluded_artists'] = int(artist_mask.sum())
        if verbose:
            found = df[artist_mask]['artist_name'].unique()
            print(f"  Excluded artists found: {len(found)}")
    else:
        artist_mask = pd.Series([False] * len(df))
        stats['removed']['excluded_artists'] = 0
    
    # Filter excluded genres
    if 'genre' in df.columns:
        genre_mask = df['genre'].isin(EXCLUDED_GENRES)
        stats['removed']['excluded_genres'] = int(genre_mask.sum())
        if verbose:
            for g in EXCLUDED_GENRES:
                count = (df['genre'] == g).sum()
                if count > 0:
                    print(f"  Genre '{g}': {count:,} tracks")
    else:
        genre_mask = pd.Series([False] * len(df))
        stats['removed']['excluded_genres'] = 0
    
    # Filter remixes
    if not keep_remixes and 'track_name' in df.columns:
        remix_mask = df['track_name'].astype(str).str.contains(REMIX_PATTERN, na=False)
        stats['removed']['remixes'] = int(remix_mask.sum())
    else:
        remix_mask = pd.Series([False] * len(df))
        stats['removed']['remixes'] = 0
    
    # Apply content filters
    combined_mask = artist_mask | genre_mask | remix_mask
    df_filtered = df[~combined_mask].copy()
    
    # Filter by minimum songs per artist
    if min_songs > 1 and 'artist_name' in df_filtered.columns:
        artist_counts = df_filtered['artist_name'].value_counts()
        keep_artists = artist_counts[artist_counts >= min_songs].index
        before_min = len(df_filtered)
        df_filtered = df_filtered[df_filtered['artist_name'].isin(keep_artists)]
        stats['removed']['min_songs'] = before_min - len(df_filtered)
        if verbose:
            removed_artists = (artist_counts < min_songs).sum()
            print(f"  Artists with < {min_songs} songs: {removed_artists:,}")
    else:
        stats['removed']['min_songs'] = 0
    
    stats['final_tracks'] = len(df_filtered)
    stats['final_artists'] = df_filtered['artist_name'].nunique() if 'artist_name' in df_filtered.columns else 0
    stats['total_removed'] = original_count - len(df_filtered)
    
    if not dry_run:
        print(f"Saving to {output_path}...")
        if output_path.suffix == '.zip' or str(output_path).endswith('.csv.zip'):
            df_filtered.to_csv(output_path, index=False, compression='zip')
        else:
            df_filtered.to_csv(output_path, index=False)
    
    return stats


def main() -> None:
    args = parse_args()
    
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    
    stats = filter_data(
        input_path=args.input,
        output_path=args.output,
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
        print(f"\nOutput: {args.output}")
        print(f"Next: python process_data.py -i {args.output}")


if __name__ == "__main__":
    main()
