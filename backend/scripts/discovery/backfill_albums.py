#!/usr/bin/env python3
"""
Backfill missing albums for artists already in the dataset.

Usage:
    # Check top 50 artists (by track count) for missing albums
    python backfill_albums.py
    
    # Check all artists (can take a while)
    python backfill_albums.py --all
    
    # Check specific number of artists
    python backfill_albums.py --limit 100
    
    # Only check artists with fewer than N tracks
    python backfill_albums.py --max-tracks 10
    
    # Actually add missing albums
    python backfill_albums.py --update
    
    # Skip artists that have been fully checked recently (uses cache)
    python backfill_albums.py --use-cache
    
    # Show progress details
    python backfill_albums.py -v

Features:
    - Prioritizes artists with fewest tracks (likely missing albums)
    - Caches fully-covered artists to skip on future runs
    - Shows summary of missing albums per artist
    - Batches API requests efficiently
"""
import os
import sys
import argparse
import time
import json
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime
from collections import defaultdict

import polars as pl
import requests

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))


from utils import (
    resolve_genre,
    load_existing,
    save_parquet,
    search_artist,
    add_tracks_for_artist,
    ReccoBeatsClient,
    OUTPUT_PARQUET,
    DEFAULT_TRACKS_PER_ARTIST,
)
CACHE_FILE = ".backfill_cache.json"


def load_cache() -> Dict:
    """Load cache of fully-covered artists."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"fully_covered": {}, "last_checked": {}}


def save_cache(cache: Dict) -> None:
    """Save cache to disk."""
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def get_artists_to_check(
    df_all: pl.DataFrame,
    limit: Optional[int] = None,
    max_tracks: Optional[int] = None,
    use_cache: bool = False,
    cache: Optional[Dict] = None,
) -> List[Tuple[str, int]]:
    """Get list of (artist_name, track_count) to check, sorted by priority."""
    
    artist_counts = df_all.group_by("artist_name").agg(pl.len().alias("count")).sort("count")
    
    artists = []
    for row in artist_counts.iter_rows(named=True):
        name = row["artist_name"]
        count = row["count"]
        
        if max_tracks and count > max_tracks:
            continue
        
        if use_cache and cache and name in cache.get("fully_covered", {}):
            last_check = cache["fully_covered"][name]
            days_ago = (datetime.now() - datetime.fromisoformat(last_check)).days
            if days_ago < 30:
                continue
        
        artists.append((name, count))
    
    if limit:
        artists = artists[:limit]
    
    return artists


def main():
    parser = argparse.ArgumentParser(description="Backfill missing albums for dataset artists")
    parser.add_argument("--limit", type=int, default=50, help="Max artists to check (default: 50)")
    parser.add_argument("--all", action="store_true", help="Check all artists (ignores --limit)")
    parser.add_argument("--max-tracks", type=int, help="Only check artists with fewer than N tracks")
    parser.add_argument("--update", action="store_true", help="Add missing albums to dataset")
    parser.add_argument("--use-cache", action="store_true", help="Skip recently checked artists")
    parser.add_argument("--clear-cache", action="store_true", help="Clear the backfill cache")
    parser.add_argument("--include-singles", action="store_true", help="Include singles when adding tracks")
    parser.add_argument("--keep-all", action="store_true", help="Add ALL tracks from albums (skip sampling)")
    parser.add_argument("--quota", type=int, default=DEFAULT_TRACKS_PER_ARTIST, help="Target total tracks per artist (default: 25)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    if args.clear_cache:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            print("Cache cleared")
        else:
            print("No cache file found")
        return
    
    cache = load_cache() if args.use_cache else {"fully_covered": {}, "last_checked": {}}
    
    df_main, df_added = load_existing()
    df_all = pl.concat([df_main, df_added])
    existing_track_ids = set(df_all["track_id"].drop_nulls().unique().to_list())
    
    print(f"Dataset: {len(df_main)} tracks ({df_main['artist_name'].n_unique()} artists)")
    print(f"Added: {len(df_added)} tracks ({df_added['artist_name'].n_unique() if len(df_added) > 0 else 0} artists)")
    
    limit = None if args.all else args.limit
    artists = get_artists_to_check(df_all, limit, args.max_tracks, args.use_cache, cache)
    
    print(f"\nChecking {len(artists)} artists (quota: {args.quota})...")
    
    if not args.update:
        print("DRY-RUN MODE (use --update to add tracks)\n")
    
    client = ReccoBeatsClient()
    needs_backfill = []
    at_quota = []
    failed = []
    
    for i, (name, track_count) in enumerate(artists):
        print(f"[{i+1}/{len(artists)}] {name} ({track_count} tracks)...", end=" ", flush=True)
        
        # Check if already at quota
        if track_count >= args.quota and not args.keep_all:
            print(f"+ At quota ({args.quota})")
            at_quota.append(name)
            cache["fully_covered"][name] = datetime.now().isoformat()
            continue
        
        try:
            result = search_artist(name, client=client, quiet=True, verbose=args.verbose)
            if not result:
                print("X Not found")
                failed.append(name)
                continue
            
            recco_uuid = result.recco_uuid
            found_name = result.name
            needed = args.quota - track_count
            
            print(f"- Needs {needed} more tracks")
            needs_backfill.append({
                "name": found_name,
                "recco_uuid": recco_uuid,
                "current_tracks": track_count,
                "needed": needed,
            })
            
            cache["last_checked"][name] = datetime.now().isoformat()
            
        except Exception as e:
            print(f"X Error: {e}")
            failed.append(name)
        
        time.sleep(0.2)
    
    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"At quota ({args.quota}+ tracks): {len(at_quota)}")
    print(f"Need backfill: {len(needs_backfill)}")
    print(f"Failed to check: {len(failed)}")
    
    if needs_backfill:
        print(f"\nArtists needing tracks:")
        for a in sorted(needs_backfill, key=lambda x: x["needed"], reverse=True)[:20]:
            print(f"  {a['name'][:35]:<35} {a['current_tracks']:>3} → {args.quota} ({a['needed']:+d})")
    
    if args.use_cache:
        save_cache(cache)
        print(f"\nCache updated ({len(cache['fully_covered'])} at quota)")
    
    if not args.update:
        print(f"\nTo add tracks, run with --update")
        return
    
    if not needs_backfill:
        print("\nNo artists need backfill")
        return
    
    print(f"\n{'=' * 60}")
    print(f"BACKFILLING TRACKS (keep_all={args.keep_all})")
    print(f"{'=' * 60}")
    
    total_added = 0
    artists_updated = 0
    
    for artist_info in sorted(needs_backfill, key=lambda x: x["needed"], reverse=True):
        name = artist_info["name"]
        recco_uuid = artist_info["recco_uuid"]
        current = artist_info["current_tracks"]
        
        print(f"\n{name} ({current} → {args.quota}):")
        
        genre = resolve_genre(name, skip_unknown=False, verbose=args.verbose)
        if not genre:
            existing_rows = df_all.filter(pl.col("artist_name") == name)["genre"].drop_nulls()
            if len(existing_rows) > 0:
                genre = existing_rows[0]
                print(f"  Genre: {genre} (from existing)")
            else:
                genre = "pop"
                print(f"  Genre: {genre} (default)")
        
        df_added, added_count = add_tracks_for_artist(
            client=client,
            artist_name=name,
            recco_uuid=recco_uuid,
            genre=genre,
            df_main=df_main,
            df_added=df_added,
            existing_track_ids=existing_track_ids,
            target_track_count=args.quota,
            include_singles=args.include_singles,
            keep_all=args.keep_all,
            skip_variants=True,
            verbose=args.verbose,
        )
        
        if added_count > 0:
            print(f"  + Added {added_count} tracks (now: {current + added_count})")
            total_added += added_count
            artists_updated += 1
        else:
            print(f"  = No new tracks found")
        
        time.sleep(0.2)
    
    if total_added > 0:
        save_parquet(df_added)
    
    print(f"\n{'=' * 60}")
    print(f"+ Added {total_added} tracks for {artists_updated} artists")
    print(f"+ Total in added_artists.parquet: {len(df_added)} tracks")
    print(f"\nRun process_data.py to merge with main dataset")


if __name__ == "__main__":
    main()
