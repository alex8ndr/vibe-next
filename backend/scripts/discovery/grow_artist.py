#!/usr/bin/env python3
"""
Grow an existing artist's track count in added_artists.parquet.

Use this when an artist already exists in the dataset but you want more tracks.
Simple top-tracks approach like add_artist.py (NOT complex album-checking like
check_new_albums.py).

Usage:
    # Add 20 more tracks for artist (default)
    python grow_artist.py "Radiohead"
    python grow_artist.py "Radiohead" --count 30
    
    # From track URL (identifies artist from track)
    python grow_artist.py --track "https://open.spotify.com/track/xxx"
    
    # Ensure specific songs are included (if available)
    python grow_artist.py "Radiohead" --songs "Creep, Paranoid Android, No Surprises"
    
    # Multiple artists
    python grow_artist.py "Radiohead, Coldplay"
    
    # Actually save changes (dry-run by default)
    python grow_artist.py "Radiohead" --update

Features:
    - Fetches top tracks from ReccoBeats (simple, like add_artist.py)
    - Filters out tracks already in dataset
    - Prioritizes specific songs if --songs specified
    - Uses weighted sampling for diversity
    - Dry-run by default with --update to save

Output:
    Modifies added_artists.parquet (only).
    Run process_data.py to merge with main dataset.
"""
import sys
import argparse
import time
from pathlib import Path
from typing import List, Optional, Tuple, Set

import polars as pl

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import (
    ReccoBeatsClient,
    get_cached_genre,
    search_artist,
    extract_spotify_id,
    load_existing,
    save_parquet,
    backfill_artist_quota,
    get_artist_unique_count,
    DEFAULT_DIVERSITY_WEIGHT,
)


def resolve_artist_from_track(
    client: ReccoBeatsClient,
    spotify_id: str,
    verbose: bool = False,
) -> Optional[Tuple[str, str]]:
    """Resolve artist name and ReccoBeats UUID from a Spotify track ID.
    
    Returns:
        Tuple of (artist_name, recco_uuid) or None if not found
    """
    tracks = client.get_tracks([spotify_id])
    if not tracks:
        print(f"  Track not found: {spotify_id}")
        return None
    
    track = tracks[0]
    artists = track.get("artists", [])
    if not artists:
        print(f"  No artist found on track")
        return None
    
    artist = artists[0]
    artist_name = artist.get("name")
    artist_uuid = artist.get("id")
    
    if not artist_uuid:
        print(f"  No artist UUID found")
        return None
    
    if verbose:
        print(f"  Track: {track.get('trackTitle', '?')}")
        print(f"  Artist: {artist_name}")
    
    return artist_name, artist_uuid


def resolve_artist_from_name(
    client: ReccoBeatsClient,
    name: str,
    verbose: bool = False,
) -> Optional[Tuple[str, str]]:
    """Resolve artist name and ReccoBeats UUID from artist name.
    
    Returns:
        Tuple of (artist_name, recco_uuid) or None if not found
    """
    result = search_artist(name, client=client, quiet=not verbose, verbose=verbose)
    if not result:
        return None
    
    return result.name, result.recco_uuid


def grow_artist(
    client: ReccoBeatsClient,
    artist_name: str,
    recco_uuid: str,
    count: int,
    songs: Optional[List[str]],
    existing_track_ids: Set[str],
    df_main: pl.DataFrame,
    df_added: pl.DataFrame,
    verbose: bool = False,
) -> Tuple[pl.DataFrame, int]:
    """Grow an artist's track count by fetching more top tracks.
    
    This is a wrapper around backfill_artist_quota() that treats count as ADDITIVE
    (adds N more tracks) rather than as a total target.
    
    Args:
        client: ReccoBeatsClient instance
        artist_name: Canonical artist name
        recco_uuid: ReccoBeats artist UUID
        count: Number of new tracks to ADD
        songs: Optional list of song names to prioritize
        existing_track_ids: Set of track IDs already in dataset
        df_main: Main dataset DataFrame
        df_added: Added artists DataFrame
        verbose: Print progress
        
    Returns:
        Tuple of (updated df_added, number of tracks added)
    """
    df_all = pl.concat([df_main, df_added])
    current_count = get_artist_unique_count(df_all, artist_name)
    print(f"  Current tracks in dataset: {current_count}")
    
    # Get genre from cache or existing data
    genre = get_cached_genre(artist_name)
    if not genre:
        existing_genre = df_all.filter(
            pl.col("artist_name").str.to_lowercase() == artist_name.lower()
        ).select("genre").head(1)
        if len(existing_genre) > 0:
            genre = existing_genre["genre"][0]
        else:
            genre = "unknown"
    
    if verbose:
        print(f"  Genre: {genre}")
    
    # Calculate TOTAL target (current + additive count)
    target_track_count = current_count + count
    
    return backfill_artist_quota(
        client=client,
        artist_name=artist_name,
        recco_uuid=recco_uuid,
        genre=genre,
        df_main=df_main,
        df_added=df_added,
        existing_track_ids=existing_track_ids,
        target_track_count=target_track_count,
        diversity_weight=DEFAULT_DIVERSITY_WEIGHT,
        prioritize_songs=songs,
        verbose=verbose,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Grow existing artist's track count in added_artists.parquet"
    )
    parser.add_argument(
        "artists", nargs="?",
        help="Artist name(s), comma-separated"
    )
    parser.add_argument(
        "--track",
        help="Spotify track URL to identify artist"
    )
    parser.add_argument(
        "--count", type=int, default=20,
        help="Number of tracks to add (default: 20)"
    )
    parser.add_argument(
        "--songs",
        help="Comma-separated song names to prioritize"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="Actually save changes (dry-run by default)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print detailed info"
    )
    args = parser.parse_args()
    
    if not args.artists and not args.track:
        parser.print_help()
        print("\nError: Provide artist name(s) or --track URL")
        sys.exit(1)
    
    df_main, df_added = load_existing()
    
    existing_track_ids = set(
        pl.concat([df_main, df_added])["track_id"].drop_nulls().unique().to_list()
    )
    
    print(f"Dataset: {len(df_main)} tracks ({df_main['artist_name'].n_unique() if len(df_main) > 0 else 0} artists)")
    print(f"Added: {len(df_added)} tracks ({df_added['artist_name'].n_unique() if len(df_added) > 0 else 0} artists)\n")
    
    if not args.update:
        print("DRY-RUN MODE: Use --update to save changes\n")
    
    client = ReccoBeatsClient()
    
    artists_to_process: List[Tuple[str, str]] = []
    
    if args.track:
        spotify_id, _ = extract_spotify_id(args.track)
        print(f"Resolving artist from track: {spotify_id}")
        result = resolve_artist_from_track(client, spotify_id, args.verbose)
        if result:
            artists_to_process.append(result)
        else:
            print("Could not resolve artist from track")
            sys.exit(1)
    else:
        names = [n.strip() for n in args.artists.split(",") if n.strip()]
        for name in names:
            print(f"Resolving: {name}")
            result = resolve_artist_from_name(client, name, args.verbose)
            if result:
                artists_to_process.append(result)
                print(f"  Found: {result[0]}")
            else:
                print(f"  Not found")
    
    if not artists_to_process:
        print("\nNo artists to process")
        sys.exit(1)
    
    songs = None
    if args.songs:
        songs = [s.strip() for s in args.songs.split(",") if s.strip()]
    
    initial_added_count = len(df_added)
    total_new_tracks = 0
    tracks_by_artist = {}
    
    print()
    for i, (artist_name, recco_uuid) in enumerate(artists_to_process):
        print(f"[{i+1}/{len(artists_to_process)}] Growing: {artist_name}")
        
        df_added, added_count = grow_artist(
            client=client,
            artist_name=artist_name,
            recco_uuid=recco_uuid,
            count=args.count,
            songs=songs,
            existing_track_ids=existing_track_ids,
            df_main=df_main,
            df_added=df_added,
            verbose=args.verbose,
        )
        
        if added_count > 0:
            print(f"  + {added_count} new tracks")
            total_new_tracks += added_count
            tracks_by_artist[artist_name] = added_count
        else:
            print(f"  No new tracks added")
        
        if i < len(artists_to_process) - 1:
            time.sleep(0.3)
    
    if total_new_tracks == 0:
        print("\nNo new tracks to add")
        return
    
    print(f"\nTotal new: {total_new_tracks} tracks")
    
    if not args.update:
        print(f"\n--- DRY-RUN PREVIEW ---")
        print(f"Would save: {len(df_added)} tracks ({df_added['artist_name'].n_unique()} artists)")
        print(f"\nNew tracks by artist:")
        for artist, count in tracks_by_artist.items():
            artist_df = df_added.filter(pl.col("artist_name") == artist)
            genre = artist_df["genre"][0] if len(artist_df) > 0 else "unknown"
            print(f"  {artist}: {count} tracks ({genre})")
        print("\nRun with --update to save changes.")
        return
    
    save_parquet(df_added)
    print(f"\n✓ Saved: {len(df_added)} tracks ({df_added['artist_name'].n_unique()} artists)")
    print(f"\nRun process_data.py to merge with main dataset")


if __name__ == "__main__":
    main()
