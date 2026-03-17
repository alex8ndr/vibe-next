#!/usr/bin/env python3
"""
Discover and add related artists using Last.fm similar artist API.

Usage:
    # Discover from specific seed artists (multiple formats supported)
    python expand_artists.py "Radiohead"
    python expand_artists.py "Radiohead, Bjork, Portishead"
    python expand_artists.py --seeds "Radiohead,Bjork,Portishead"
    
    # Discover artists related to top artists in your dataset
    python expand_artists.py
    
    # Limit expansion depth
    python expand_artists.py --limit 20
    
    # Actually add discovered artists
    python expand_artists.py "Radiohead" --update
    
    # Set minimum match score (0-1)
    python expand_artists.py --min-match 0.5
    
    # Skip artists with unknown genre (default: True)
    python expand_artists.py --skip-unknown-genre
    
    # Try to infer genre from related artists (slower)
    python expand_artists.py --infer-genre

Requires:
    Set LASTFM_API_KEY environment variable (free at last.fm/api)

Features:
    - Expands from seed artists using Last.fm artist.getSimilar
    - Filters out artists already in dataset
    - Ranks by match score and number of seed connections
    - Uses weighted track sampling for diverse selection
    - Skips artists with unknown genre by default
"""
import os
import sys
import argparse
import time
from pathlib import Path
from typing import List, Dict, Optional, Set

import polars as pl

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from track_dedup import deduplicate_tracks_polars, normalize_artist_name
from utils import (
    LastFmClient,
    add_discovered_artist,
    load_existing,
    save_parquet,
    deduplicate_with_report,
    OUTPUT_PARQUET,
    DEFAULT_TRACKS_PER_ARTIST,
    DEFAULT_DIVERSITY_WEIGHT,
)


def get_seed_artists(
    df_all: pl.DataFrame,
    explicit_seeds: Optional[List[str]] = None,
    top_n: int = 20,
) -> List[str]:
    """Get seed artists for expansion.
    
    If explicit_seeds provided, use those.
    Otherwise, pick top N artists by track count from dataset.
    """
    if explicit_seeds:
        existing = set(df_all["artist_name"].drop_nulls().unique().to_list())
        valid = [s for s in explicit_seeds if s in existing]
        invalid = [s for s in explicit_seeds if s not in existing]
        if invalid:
            print(f"Warning: {len(invalid)} seeds not in dataset: {', '.join(invalid[:5])}")
        return valid if valid else explicit_seeds
    
    artist_counts = df_all.group_by("artist_name").agg(pl.len().alias("count")).sort("count", descending=True)
    return artist_counts.head(top_n)["artist_name"].to_list()


def main():
    parser = argparse.ArgumentParser(description="Discover and add related artists via Last.fm")
    parser.add_argument("artists", nargs="?", help="Seed artist name(s), comma-separated")
    parser.add_argument("--seeds", help="Seed artist names (alternative to positional arg)")
    parser.add_argument("--limit", type=int, default=20, help="Max artists to discover")
    parser.add_argument("--min-match", type=float, default=0.4, help="Minimum Last.fm match score (0-1)")
    parser.add_argument("--tracks", type=int, default=DEFAULT_TRACKS_PER_ARTIST, help="Tracks per artist")
    parser.add_argument("--diversity", type=float, default=DEFAULT_DIVERSITY_WEIGHT, help="Track diversity weight (0-1)")
    parser.add_argument("--update", action="store_true", help="Actually add artists to dataset")
    parser.add_argument("--skip-unknown-genre", action="store_true", default=True, 
                        help="Skip artists with unknown genre (default)")
    parser.add_argument("--no-skip-unknown", action="store_true", 
                        help="Don't skip artists with unknown genre")
    parser.add_argument("--infer-genre", action="store_true", 
                        help="Try to infer genre from related artists")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    lastfm_client = LastFmClient()
    if not lastfm_client.api_key:
        print("Error: LASTFM_API_KEY environment variable not set")
        print("Get a free API key at: https://www.last.fm/api/account/create")
        sys.exit(1)
    
    df_main, df_added = load_existing()
    df_all = pl.concat([df_main, df_added])
    existing_track_ids = set(df_all["track_id"].drop_nulls().unique().to_list())
    # Use normalized artist names for case/accent-insensitive comparison
    existing_artists = {normalize_artist_name(a) for a in df_all["artist_name"].drop_nulls().unique().to_list()}
    
    print(f"Dataset: {len(df_main)} tracks ({df_main['artist_name'].n_unique()} artists)")
    print(f"Added: {len(df_added)} tracks ({df_added['artist_name'].n_unique() if len(df_added) > 0 else 0} artists)")
    
    # Accept seeds from positional arg or --seeds flag
    seed_input = args.artists or args.seeds
    seeds = [s.strip() for s in seed_input.split(",") if s.strip()] if seed_input else None
    seed_artists = get_seed_artists(df_all, seeds)
    
    print(f"\nUsing {len(seed_artists)} seed artists for expansion")
    if args.verbose:
        print(f"Seeds: {', '.join(seed_artists[:10])}" + ("..." if len(seed_artists) > 10 else ""))
    
    print(f"\nDiscovering related artists via Last.fm...")
    candidates = lastfm_client.expand_artist_pool(
        seed_artists,
        existing_artists,
        limit=args.limit * 2,
        min_match=args.min_match,
    )
    
    if not candidates:
        print("No new artists discovered")
        return
    
    print(f"\nFound {len(candidates)} candidate artists:")
    for c in candidates[:20]:
        connections = f" (via {c['count']} seeds)" if c['count'] > 1 else f" (via {c['seed']})"
        print(f"  {c['name'][:40]:<40} match: {c['match']:.2f}{connections}")
    
    if len(candidates) > 20:
        print(f"  ... and {len(candidates) - 20} more")
    
    if not args.update:
        print(f"\nDRY-RUN MODE (use --update to add artists)")
        return
    
    print(f"\n{'=' * 60}")
    print(f"ADDING ARTISTS")
    print(f"{'=' * 60}")
    
    skip_unknown = not args.no_skip_unknown
    all_new_rows = []
    added_count = 0
    skipped_genre = 0
    
    for candidate in candidates[:args.limit]:
        name = candidate["name"]
        print(f"\n  {name}...")
        
        try:
            df_rows = add_discovered_artist(
                name,
                existing_track_ids,
                skip_unknown=skip_unknown,
                use_infer=args.infer_genre,
                tracks_per_artist=args.tracks,
                diversity_weight=args.diversity,
                verbose=args.verbose,
                lastfm_client=lastfm_client,
            )
            
            if df_rows is None:
                if skip_unknown:
                    skipped_genre += 1
                continue
            
            if len(df_rows) == 0:
                print(f"    X No tracks found")
                continue
            
            genre = df_rows['genre'][0]
            print(f"    + Added {len(df_rows)} tracks ({genre})")
            
            all_new_rows.append(df_rows)
            added_count += 1
            
            for tid in df_rows['track_id'].drop_nulls().to_list():
                existing_track_ids.add(tid)
            existing_artists.add(normalize_artist_name(name))
            
        except Exception as e:
            print(f"    X Error: {e}")
        
        time.sleep(0.5)
    
    if not all_new_rows:
        print("\nNo artists added")
        if skipped_genre > 0:
            print(f"  ({skipped_genre} skipped due to unknown genre)")
        return
    
    df_new = pl.concat(all_new_rows)
    df_combined = pl.concat([df_added, df_new])
    df_combined, removed = deduplicate_with_report(df_combined, df_main)
    
    save_parquet(df_combined)
    print(f"\n{'=' * 60}")
    print(f"+ Added {added_count} artists ({len(df_new)} tracks)")
    if skipped_genre > 0:
        print(f"  ({skipped_genre} skipped due to unknown genre)")
    print(f"+ Total in added_artists.parquet: {len(df_combined)} tracks")
    print(f"\nRun process_data.py to merge with main dataset")


if __name__ == "__main__":
    main()
