#!/usr/bin/env python3
"""
Check an artist for new albums not in the dataset and optionally update.

Usage:
    # Check what albums are missing (dry-run by default)
    python check_new_albums.py "Radiohead"
    python check_new_albums.py "Radiohead, Coldplay"
    python check_new_albums.py --names "Radiohead, Coldplay"
    python check_new_albums.py --url "https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb"
    
    # Actually add missing albums
    python check_new_albums.py "Radiohead" --update
    
    # Check multiple artists from file
    python check_new_albums.py --file artists.txt
    
    # Batch update multiple artists
    python check_new_albums.py --file artists.txt --update
    
    # Show all albums (not just missing)
    python check_new_albums.py "Radiohead" --all
    
    # Limit albums to check (newest first)
    python check_new_albums.py "Radiohead" --limit 5

Features:
    - Searches artist via Deezer → Songlink → ReccoBeats
    - Fetches artist's full discography from ReccoBeats
    - Compares album track_ids with dataset to find missing albums
    - Shows release date, track count, and which tracks are missing
    - Can add missing albums to added_artists.parquet
"""
import os
import sys
import argparse
import time
import re
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime

import polars as pl
import requests

# Patterns for album variants we want to skip (for singles)
SKIP_SINGLE_PATTERNS = [
    r'\bremix(es)?\b',
    r'\bacoustic\s*(version|collection)?\b',
    r'\blive\s*(at|from|in|version)?\b',
    r'\bremaster(ed)?\b',
    r'\bkaraoke\b',
    r'\binstrumental\s*version\b',
]
SKIP_SINGLE_RE = re.compile('|'.join(SKIP_SINGLE_PATTERNS), re.IGNORECASE)

# Patterns to skip for any album type
SKIP_ALBUM_PATTERNS = [
    r'\btrack\s*by\s*track\b',
]
SKIP_ALBUM_RE = re.compile('|'.join(SKIP_ALBUM_PATTERNS), re.IGNORECASE)

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from track_dedup import deduplicate_tracks_polars
from utils import (
    ReccoBeatsClient,
    search_artist,
    extract_spotify_id,
    load_existing,
    save_parquet,
    add_tracks_for_artist,
    resolve_genre,
    weighted_track_sample,
    build_rows,
    deduplicate_with_report,
    RECCOBEATS_URL,
    OUTPUT_PARQUET,
    DEFAULT_TRACKS_PER_ARTIST,
    DEFAULT_DIVERSITY_WEIGHT,
)


def get_recco_artist_from_spotify_track_id(client: ReccoBeatsClient, spotify_track_id: str) -> Optional[Tuple[str, str]]:
    """Get ReccoBeats artist UUID and name from a Spotify track ID.
    Returns (recco_uuid, artist_name) or None.
    """
    tracks = client.get_tracks([spotify_track_id])
    if not tracks:
        return None
    track = tracks[0]
    artists = track.get("artists", [])
    if not artists:
        return None
    # The href is the Spotify artist URL, extract the Spotify artist ID
    artist_href = artists[0].get("href", "")
    spotify_artist_id = artist_href.split("/")[-1] if artist_href else None
    if not spotify_artist_id:
        return None
    
    # Look up the artist by Spotify ID to get ReccoBeats UUID
    url = f"{RECCOBEATS_URL}/artist"
    r = requests.get(url, params={"ids": spotify_artist_id}, timeout=20)
    r.raise_for_status()
    artist_data = r.json().get("content", [])
    if not artist_data:
        return None
    
    recco_uuid = artist_data[0].get("id")
    artist_name = artist_data[0].get("name", "Unknown")
    return (recco_uuid, artist_name)


def search_artist_by_name(name: str, verbose: bool = False) -> Optional[Tuple[str, str]]:
    """Search for artist by name using the unified search_artist function.
    Returns (recco_uuid, artist_name) or None.
    """
    result = search_artist(name, quiet=not verbose, verbose=verbose)
    if result:
        return (result.recco_uuid, result.name)
    return None


def search_artist_by_url(url_input: str, verbose: bool = False) -> Optional[Tuple[str, str]]:
    """Get artist from Spotify artist/track/album URL.
    Returns (recco_uuid, artist_name) or None.
    """
    spotify_id, item_type = extract_spotify_id(url_input)
    client = ReccoBeatsClient()
    
    if "artist" in url_input:
        # Direct artist lookup by Spotify ID
        api_url = f"{RECCOBEATS_URL}/artist"
        r = requests.get(api_url, params={"ids": spotify_id}, timeout=20)
        r.raise_for_status()
        artists = r.json().get("content", [])
        if artists:
            artist = artists[0]
            recco_uuid = artist.get("id")  # ReccoBeats UUID
            return (recco_uuid, artist.get("name", "Unknown"))
    
    if item_type == "album":
        album = client.get_album(spotify_id)
        if album:
            artists = album.get("artists", [])
            if artists:
                # Get the Spotify artist ID from href, then look up ReccoBeats UUID
                artist_href = artists[0].get("href", "")
                spotify_artist_id = artist_href.split("/")[-1] if artist_href else None
                if spotify_artist_id:
                    api_url = f"{RECCOBEATS_URL}/artist"
                    r = requests.get(api_url, params={"ids": spotify_artist_id}, timeout=20)
                    r.raise_for_status()
                    artist_data = r.json().get("content", [])
                    if artist_data:
                        return (artist_data[0].get("id"), artist_data[0].get("name", "Unknown"))
    
    # For track URLs, use the track lookup function
    return get_recco_artist_from_spotify_track_id(client, spotify_id)


def _date_key(date_str: str) -> int:
    """Convert date string to sortable int (YYYYMMDD)."""
    try:
        return int(date_str.replace("-", "")[:8])
    except (ValueError, TypeError):
        return 19000101


def _normalize_album_name(name: str) -> str:
    """Normalize album name for deduplication.
    
    Uses same approach as track_dedup: variants ADD to the original name,
    so strip everything after the first delimiter.
    """
    from track_dedup import VARIANT_DELIMITERS, _normalize_quotes
    
    if not name:
        return ""
    
    name = _normalize_quotes(name)
    name = ' '.join(name.lower().split())
    
    # Also treat " + " as a delimiter (common for "Album + Bonus Tracks")
    album_delimiters = VARIANT_DELIMITERS + (' + ',)
    
    for delim in album_delimiters:
        if delim in name:
            name = name.split(delim)[0]
    
    return name.strip()


def _should_skip_album(album_name: str, album_type: str, skip_variants: bool) -> Tuple[bool, str]:
    """Check if album should be skipped. Returns (should_skip, reason)."""
    if not skip_variants:
        return False, ""
    
    # Skip remix/acoustic/etc singles
    if album_type == "single" and SKIP_SINGLE_RE.search(album_name):
        return True, "variant single"
    
    # Skip patterns that apply to any album type
    if SKIP_ALBUM_RE.search(album_name):
        return True, "variant album"
    
    return False, ""


def check_artist_albums(
    recco_uuid: str,
    artist_name: str,
    existing_track_ids: Set[str],
    limit: Optional[int] = None,
    show_all: bool = False,
    verbose: bool = False,
    skip_variants: bool = True,
    include_singles: bool = False,
) -> Tuple[List[Dict], List[Dict]]:
    """Check which albums are missing from the dataset.
    
    Args:
        skip_variants: If True, skip remix singles, acoustic versions, track-by-track, etc.
        include_singles: If True, include singles in the scan. Default False (albums only).
    
    Returns: (missing_albums, all_albums)
    """
    client = ReccoBeatsClient()
    albums = client.get_artist_albums(recco_uuid)
    
    # First, deduplicate by normalized name - prefer shortest (base) album
    # Group albums by their normalized name
    by_norm_name = {}
    for album in albums:
        norm = _normalize_album_name(album.get("name", ""))
        if norm not in by_norm_name:
            by_norm_name[norm] = []
        by_norm_name[norm].append(album)
    
    # For each group, pick the one with shortest name (base album)
    deduped_albums = []
    for norm, group in by_norm_name.items():
        # Sort by name length (shortest first), then by date (newest first)
        group_sorted = sorted(group, key=lambda a: (len(a.get("name", "")), -_date_key(a.get("releaseDate", "1900-01-01"))))
        deduped_albums.append(group_sorted[0])
    
    # Sort final list by date (newest first)
    albums_sorted = sorted(
        deduped_albums,
        key=lambda a: a.get("releaseDate", "1900-01-01"),
        reverse=True
    )
    
    if limit:
        albums_sorted = albums_sorted[:limit]
    
    missing_albums = []
    all_album_info = []
    
    skipped_count = 0
    
    for album in albums_sorted:
        album_name = album.get("name", "Unknown")
        album_uuid = album.get("id")  # ReccoBeats UUID (not href which is Spotify URL)
        album_href = album.get("href", "")
        spotify_album_id = album_href.split("/")[-1] if album_href else None
        release_date = album.get("releaseDate", "Unknown")
        album_type = album.get("albumType", "album")
        
        if not album_uuid:
            continue
        
        # Skip singles unless --include-singles is passed
        if album_type == "single" and not include_singles:
            if verbose:
                print(f"    Skipping (single): {album_name}")
            skipped_count += 1
            continue
        
        # Skip variant albums (remixes, acoustic, track-by-track, etc.)
        should_skip, skip_reason = _should_skip_album(album_name, album_type, skip_variants)
        if should_skip:
            if verbose:
                print(f"    Skipping ({skip_reason}): {album_name}")
            skipped_count += 1
            continue
        
        tracks = client.get_album_tracks(album_uuid)
        track_ids = []
        for t in tracks:
            # Track href is Spotify URL, extract the Spotify track ID
            href = t.get("href", "")
            tid = href.split("/")[-1] if href else None
            if tid:
                track_ids.append(tid)
        
        existing_count = sum(1 for tid in track_ids if tid in existing_track_ids)
        missing_count = len(track_ids) - existing_count
        
        album_info = {
            "name": album_name,
            "uuid": album_uuid,  # ReccoBeats UUID for API calls
            "spotify_id": spotify_album_id,  # Spotify album ID
            "release_date": release_date,
            "type": album_type,
            "total_tracks": len(track_ids),
            "existing_tracks": existing_count,
            "missing_tracks": missing_count,
            "track_ids": track_ids,
        }
        
        all_album_info.append(album_info)
        
        # Only consider album "missing" if less than 20% of tracks are in dataset
        # This avoids re-adding albums we mostly have already
        coverage_ratio = existing_count / len(track_ids) if track_ids else 0
        if missing_count > 0 and coverage_ratio < 0.2:
            missing_albums.append(album_info)
        elif verbose and missing_count > 0:
            print(f"    Skipping (already {coverage_ratio:.0%} covered): {album_name}")
        
        time.sleep(0.1)
    
    if verbose and skipped_count:
        print(f"    Skipped {skipped_count} variant/duplicate albums")
    
    return missing_albums, all_album_info


def add_missing_albums(
    artist_name: str,
    recco_uuid: str,
    missing_albums: List[Dict],
    genre: Optional[str],
    existing_track_ids: Set[str],
    df_added: pl.DataFrame,
    df_main: pl.DataFrame,
    verbose: bool = False,
    keep_all: bool = False,
    tracks_per_album: int = 5,
    diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
) -> pl.DataFrame:
    """Add tracks from missing albums to the dataset.
    
    Args:
        keep_all: If True, add ALL tracks from each album. If False, sample a representative subset.
        tracks_per_album: Target tracks per album when sampling (default 5).
        diversity_weight: Weight for diversity vs popularity in sampling (0-1).
    """
    from schema import normalize_for_merge

    client = ReccoBeatsClient()
    all_new_rows = []

    # Normalize schemas to prevent casting errors during concat
    df_added = normalize_for_merge(df_added)
    
    for album in missing_albums:
        album_uuid = album["uuid"]
        album_name = album["name"]
        
        print(f"  Adding: {album_name} ({album['release_date']})")
        
        tracks = client.get_album_tracks(album_uuid)
        new_tracks = []
        new_track_ids = []
        
        for t in tracks:
            href = t.get("href", "")
            tid = href.split("/")[-1] if href else None
            if tid and tid not in existing_track_ids:
                new_tracks.append(t)
                new_track_ids.append(tid)
        
        if not new_tracks:
            print(f"    No new tracks")
            continue
        
        # Get audio features for all tracks (needed for sampling)
        all_track_ids = [t.get("href", "").split("/")[-1] for t in new_tracks if t.get("href")]
        features = client.get_audio_features(all_track_ids)
        
        # Sample tracks using weighted_track_sample (popularity + diversity)
        if not keep_all and len(new_tracks) > tracks_per_album:
            sampled = weighted_track_sample(
                new_tracks,
                features,
                target_count=tracks_per_album,
                diversity_weight=diversity_weight,
            )
            if verbose:
                print(f"    Sampled {len(sampled)}/{len(new_tracks)} tracks (diversity={diversity_weight})")
            new_tracks = sampled
        
        df_rows = build_rows(artist_name, new_tracks, features, genre, verbose)
        
        # Deduplicate within album (remove variants like "Song - Remastered")
        df_rows = deduplicate_tracks_polars(df_rows)
        
        if len(df_rows) > 0:
            all_new_rows.append(df_rows)
            print(f"    Added {len(df_rows)} tracks")
        
        time.sleep(0.2)
    
    if not all_new_rows:
        return df_added
    
    df_new = pl.concat(all_new_rows)
    df_combined = pl.concat([df_added, df_new])
    df_combined, removed = deduplicate_with_report(df_combined, df_main)
    
    if removed:
        print(f"  Removed {len(removed)} duplicates")
    
    return df_combined


def format_album_line(album: Dict, in_dataset: bool = False) -> str:
    """Format an album for display."""
    status = "[x]" if in_dataset else "[ ]"
    missing = f" ({album['missing_tracks']} new)" if album['missing_tracks'] > 0 else ""
    return f"  {status} {album['release_date'][:10]:10} {album['type']:8} {album['name'][:50]:<50}{missing}"


def process_artist(
    artist_input: str,
    is_url: bool,
    existing_track_ids: Set[str],
    df_main: pl.DataFrame,
    df_added: pl.DataFrame,
    update: bool,
    limit: Optional[int],
    show_all: bool,
    genre_override: Optional[str],
    verbose: bool,
    skip_variants: bool = True,
    include_singles: bool = False,
    keep_all: bool = False,
) -> Tuple[pl.DataFrame, int, int]:
    """Process a single artist. Returns (updated_df_added, albums_checked, albums_missing)."""
    client = ReccoBeatsClient()
    
    if is_url:
        result = search_artist_by_url(artist_input, verbose)
    else:
        result = search_artist_by_name(artist_input, verbose)
    
    if not result:
        print(f"X Could not find artist: {artist_input}")
        return df_added, 0, 0
    
    recco_uuid, artist_name = result
    print(f"\n{artist_name}")
    print("=" * 60)
    
    missing_albums, all_albums = check_artist_albums(
        recco_uuid, artist_name, existing_track_ids,
        limit=limit, show_all=show_all, verbose=verbose,
        skip_variants=skip_variants,
        include_singles=include_singles,
    )
    
    if show_all:
        print(f"\nAll albums ({len(all_albums)}):")
        for album in all_albums:
            in_dataset = album['missing_tracks'] == 0
            print(format_album_line(album, in_dataset))
    else:
        if missing_albums:
            print(f"\nMissing albums ({len(missing_albums)}):")
            for album in missing_albums:
                print(format_album_line(album))
        else:
            print(f"\n+ All albums in dataset ({len(all_albums)} albums)")
    
    if missing_albums and update:
        genre = genre_override
        if not genre:
            print(f"\nLooking up genre...")
            genre = resolve_genre(artist_name, skip_unknown=False, verbose=verbose)
            if genre:
                print(f"  Genre: {genre}")
            else:
                print(f"  Genre: unknown (using default)")
                genre = "pop"
        
        mode_desc = "all tracks" if keep_all else "sampled tracks"
        print(f"\nAdding {mode_desc} from {len(missing_albums)} missing albums...")
        df_added = add_missing_albums(
            artist_name=artist_name,
            recco_uuid=recco_uuid,
            missing_albums=missing_albums,
            genre=genre,
            existing_track_ids=existing_track_ids,
            df_added=df_added,
            df_main=df_main,
            verbose=verbose,
            keep_all=keep_all,
        )
    
    total_missing = sum(a['missing_tracks'] for a in missing_albums)
    return df_added, len(all_albums), len(missing_albums)


def main():
    parser = argparse.ArgumentParser(description="Check artist for new albums not in dataset")
    parser.add_argument("artist", nargs="?", help="Artist name(s), comma-separated")
    parser.add_argument("--names", help="Artist name(s), comma-separated (alternative to positional)")
    parser.add_argument("--url", help="Spotify artist/track/album URL")
    parser.add_argument("--file", help="File with artist names/URLs (one per line)")
    parser.add_argument("--update", action="store_true", help="Add missing albums to dataset")
    parser.add_argument("--limit", type=int, help="Max albums to check (newest first)")
    parser.add_argument("--all", action="store_true", dest="show_all", help="Show all albums, not just missing")
    parser.add_argument("--include-variants", action="store_true", help="Include remix/acoustic/deluxe variants (skipped by default)")
    parser.add_argument("--include-singles", action="store_true", help="Include singles when adding tracks")
    parser.add_argument("--keep-all", action="store_true", help="Add ALL tracks from albums (skip sampling)")
    parser.add_argument("--quota", type=int, default=25, help="Target total tracks per artist (default: 25)")
    parser.add_argument("--genre", help="Override genre (otherwise auto-detected)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    # Accept artist names from positional arg or --names flag
    artist_input = args.artist or args.names
    
    if not artist_input and not args.url and not args.file:
        parser.print_help()
        sys.exit(1)
    
    df_main, df_added = load_existing()
    df_all = pl.concat([df_main, df_added])
    existing_track_ids = set(df_all["track_id"].drop_nulls().unique().to_list())
    
    print(f"Dataset: {len(df_main)} tracks, Added: {len(df_added)} tracks")
    
    if not args.update:
        print("\nDRY-RUN MODE (use --update to add missing albums)\n")
    
    artists_to_check = []
    
    if args.file:
        if not os.path.exists(args.file):
            print(f"File not found: {args.file}")
            sys.exit(1)
        with open(args.file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    is_url = "spotify.com" in line or "http" in line
                    artists_to_check.append((line, is_url))
    elif args.url:
        artists_to_check.append((args.url, True))
    elif artist_input:
        # Support comma-separated artist names
        for name in artist_input.split(","):
            name = name.strip()
            if name:
                artists_to_check.append((name, False))
    
    total_checked = 0
    total_missing = 0
    
    skip_variants = not args.include_variants
    
    for artist_input, is_url in artists_to_check:
        df_added, checked, missing = process_artist(
            artist_input, is_url, existing_track_ids,
            df_main, df_added, args.update, args.limit,
            args.show_all, args.genre, args.verbose,
            skip_variants=skip_variants,
            include_singles=args.include_singles,
            keep_all=args.keep_all,
        )
        total_checked += checked
        total_missing += missing
        time.sleep(0.3)
    
    print(f"\n{'=' * 60}")
    print(f"Summary: {total_checked} albums checked, {total_missing} with missing tracks")
    
    if args.update and total_missing > 0:
        save_parquet(df_added)
        print(f"\n+ Saved {len(df_added)} tracks to added_artists.parquet")
        print("Run process_data.py to merge with main dataset")


if __name__ == "__main__":
    main()
