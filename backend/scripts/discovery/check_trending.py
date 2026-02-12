#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check trending artists from Spotify charts against the dataset.

Usage:
    # Check global top 50 (default)
    python check_trending.py
    
    # Check viral charts
    python check_trending.py --viral
    
    # Check specific country
    python check_trending.py --country us
    python check_trending.py --country gb --viral
    
    # Limit number of artists to check
    python check_trending.py --limit 20
    
    # Show more detail about missing artists
    python check_trending.py --detail
    
    # Add missing trending artists to dataset
    python check_trending.py --update
    
    # Only add artists with enough tracks available
    python check_trending.py --update --min-tracks 5

Features:
    - Fetches current Spotify chart data
    - Compares chart artists against your dataset
    - Shows which trending artists are missing
    - Can add missing artists with their top tracks
    - Supports global, country-specific, and viral charts
"""
import sys
import argparse
import time
import re
from pathlib import Path
from typing import List, Dict, Optional, Set
from collections import defaultdict

import polars as pl
import requests

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from track_dedup import normalize_artist_name
from utils import (
    add_discovered_artist,
    load_existing,
    save_parquet,
    deduplicate_with_report,
    DEEZER_URL,
    OUTPUT_PARQUET,
    DEFAULT_TRACKS_PER_ARTIST,
)

BASE_URL = "https://api.reccobeats.com/v1"

CHART_PLAYLISTS = {
    "global": "37i9dQZEVXbMDoHDwVN2tF",
    "viral_global": "37i9dQZEVXbLiRSasKsNU9",
    "us": "37i9dQZEVXbLRQDuF5jeBp",
    "viral_us": "37i9dQZEVXbKuaTI1Z1Afx",
    "gb": "37i9dQZEVXbLnolsZ8PSNw",
    "viral_gb": "37i9dQZEVXbL3DLHfQeDmV",
    "de": "37i9dQZEVXbJiZcmkrIHGU",
    "viral_de": "37i9dQZEVXbLCiSZ5E3Xid",
    "fr": "37i9dQZEVXbIPWwFssbupI",
    "viral_fr": "37i9dQZEVXbIZM8SIgu6df",
    "jp": "37i9dQZEVXbKXQ4mDTEBXq",
    "viral_jp": "37i9dQZEVXbKqiTGXuCOsB",
    "br": "37i9dQZEVXbMXbN3EUUhlg",
    "viral_br": "37i9dQZEVXbMOkSwG072hV",
    "mx": "37i9dQZEVXbO3qyFxbkOE1",
    "viral_mx": "37i9dQZEVXbLMglglvNmJo",
    "au": "37i9dQZEVXbJPcfkRz0wJ0",
    "viral_au": "37i9dQZEVXbK4fwx2r07XW",
    "ca": "37i9dQZEVXbKj23U1GF4IR",
    "viral_ca": "37i9dQZEVXbKfIuOAZrk7G",
    "in": "37i9dQZEVXbLZ52XmnySJg",
    "viral_in": "37i9dQZEVXbK4NvPi6Sxit",
    "kr": "37i9dQZEVXbNxXF4SkHj9F",
    "viral_kr": "37i9dQZEVXbJZGli0rRP3r",
}

POPULAR_CHARTS_KWORB = "https://kworb.net/spotify/artists.html"


def fetch_chart_via_reccobeats(playlist_id: str, limit: int = 50) -> List[Dict]:
    """Fetch chart playlist tracks via ReccoBeats."""
    tracks = []
    page = 0
    url = f"{BASE_URL}/track/recommendation"
    
    while len(tracks) < limit:
        try:
            r = requests.get(
                url,
                params={"seeds": playlist_id, "size": min(50, limit - len(tracks)), "page": page},
                timeout=20
            )
            if r.status_code == 404:
                return tracks
            r.raise_for_status()
            batch = r.json().get("content", [])
            if not batch:
                break
            tracks.extend(batch)
            page += 1
        except Exception as e:
            print(f"  Warning: Could not fetch chart: {e}")
            break
    
    return tracks[:limit]


def fetch_chart_via_deezer(chart_type: str = "global", limit: int = 100) -> List[Dict]:
    """Fetch chart from Deezer (fallback, works well).
    Returns list of {artist_name, track_name, spotify_id (if available)}
    """
    results = []
    
    try:
        if chart_type == "global":
            url = f"{DEEZER_URL}/chart/0/tracks"
        else:
            url = f"{DEEZER_URL}/chart/0/tracks"
        
        r = requests.get(url, params={"limit": limit}, timeout=15)
        r.raise_for_status()
        tracks = r.json().get("data", [])
        
        for track in tracks:
            artist = track.get("artist", {})
            results.append({
                "artist_name": artist.get("name", "Unknown"),
                "artist_id_deezer": artist.get("id"),
                "track_name": track.get("title", "Unknown"),
                "track_id_deezer": track.get("id"),
                "position": track.get("position", len(results) + 1),
            })
        
        return results
    except Exception as e:
        print(f"Error fetching Deezer chart: {e}")
        return []


def fetch_trending_artists_kworb(limit: int = 100) -> List[Dict]:
    """Scrape kworb.net for trending Spotify artists (public, no auth needed)."""
    results = []
    
    try:
        r = requests.get(POPULAR_CHARTS_KWORB, timeout=15)
        r.raise_for_status()
        html = r.text
        
        pattern = r'<td><a href="[^"]*">([^<]+)</a></td>'
        matches = re.findall(pattern, html)
        
        seen = set()
        for name in matches:
            if name not in seen and len(results) < limit:
                results.append({"artist_name": name, "source": "kworb"})
                seen.add(name)
        
        return results
    except Exception as e:
        print(f"Error fetching kworb data: {e}")
        return []


def fetch_chart_artists(
    chart_type: str = "top",
    country: str = "global",
    limit: int = 50,
    verbose: bool = False,
) -> List[Dict]:
    """Fetch artists from charts. Returns list of {artist_name, ...}"""
    
    if chart_type == "trending":
        print(f"Fetching trending artists from kworb.net...")
        return fetch_trending_artists_kworb(limit)
    
    print(f"Fetching {chart_type} chart ({country})...")
    
    chart_tracks = fetch_chart_via_deezer(country, limit * 2)
    
    if not chart_tracks:
        print("  Fallback: using kworb.net data")
        return fetch_trending_artists_kworb(limit)
    
    artists = {}
    for track in chart_tracks:
        name = track["artist_name"]
        if name not in artists:
            artists[name] = {
                "artist_name": name,
                "track_count": 1,
                "top_track": track["track_name"],
                "position": track.get("position", 999),
            }
        else:
            artists[name]["track_count"] += 1
    
    sorted_artists = sorted(artists.values(), key=lambda x: x["position"])
    return sorted_artists[:limit]


def get_artist_track_count(artist_name: str, existing_artists: Dict[str, int]) -> int:
    """Get number of tracks for artist in dataset (case/accent insensitive)."""
    return existing_artists.get(normalize_artist_name(artist_name), 0)


def main():
    parser = argparse.ArgumentParser(description="Check trending artists against dataset")
    parser.add_argument("--viral", action="store_true", help="Use viral chart instead of top")
    parser.add_argument("--trending", action="store_true", help="Use kworb trending artists")
    parser.add_argument("--country", default="global", help="Country code (us, gb, de, fr, etc.)")
    parser.add_argument("--limit", type=int, default=50, help="Number of chart entries to check")
    parser.add_argument("--detail", action="store_true", help="Show detailed info for each artist")
    parser.add_argument("--update", action="store_true", help="Add missing artists to dataset")
    parser.add_argument("--min-tracks", type=int, default=3, help="Min tracks available to add artist")
    parser.add_argument("--max-add", type=int, default=20, help="Max artists to add in one run")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    df_main, df_added = load_existing()
    df_all = pl.concat([df_main, df_added])
    existing_track_ids = set(df_all["track_id"].drop_nulls().unique().to_list())
    
    # Use normalized artist names for case/accent-insensitive comparison
    existing_artists = defaultdict(int)
    for name in df_all["artist_name"].drop_nulls().to_list():
        existing_artists[normalize_artist_name(name)] += 1
    
    print(f"Dataset: {len(df_main)} tracks ({df_main['artist_name'].n_unique()} artists)")
    print(f"Added: {len(df_added)} tracks ({df_added['artist_name'].n_unique() if len(df_added) > 0 else 0} artists)")
    print()
    
    if args.trending:
        chart_type = "trending"
    elif args.viral:
        chart_type = "viral"
    else:
        chart_type = "top"
    
    artists = fetch_chart_artists(chart_type, args.country, args.limit, args.verbose)
    
    if not artists:
        print("Could not fetch chart data")
        sys.exit(1)
    
    print(f"\nFound {len(artists)} artists in chart\n")
    
    in_dataset = []
    missing = []
    partial = []
    
    for artist in artists:
        name = artist["artist_name"]
        track_count = get_artist_track_count(name, existing_artists)
        
        artist["dataset_tracks"] = track_count
        
        if track_count == 0:
            missing.append(artist)
        elif track_count < 5:
            partial.append(artist)
        else:
            in_dataset.append(artist)
    
    print(f"{'=' * 60}")
    print(f"IN DATASET ({len(in_dataset)} artists, 5+ tracks):")
    print(f"{'=' * 60}")
    for a in in_dataset[:10]:
        extra = f" (top: {a['top_track'][:30]})" if 'top_track' in a and args.detail else ""
        print(f"  [x] {a['artist_name'][:40]:<40} {a['dataset_tracks']:>3} tracks{extra}")
    if len(in_dataset) > 10:
        print(f"  ... and {len(in_dataset) - 10} more")
    
    if partial:
        print(f"\n{'=' * 60}")
        print(f"PARTIAL ({len(partial)} artists, <5 tracks):")
        print(f"{'=' * 60}")
        for a in partial:
            extra = f" (top: {a['top_track'][:30]})" if 'top_track' in a and args.detail else ""
            print(f"  [~] {a['artist_name'][:40]:<40} {a['dataset_tracks']:>3} tracks{extra}")
    
    print(f"\n{'=' * 60}")
    print(f"MISSING ({len(missing)} artists):")
    print(f"{'=' * 60}")
    for a in missing:
        extra = f" (top: {a['top_track'][:30]})" if 'top_track' in a and args.detail else ""
        chart_pos = f"#{a.get('position', '?')}" if 'position' in a else ""
        print(f"  [ ] {chart_pos:>4} {a['artist_name'][:40]:<40}{extra}")
    
    coverage = len(in_dataset) / len(artists) * 100 if artists else 0
    print(f"\n{'=' * 60}")
    print(f"Coverage: {coverage:.1f}% ({len(in_dataset)}/{len(artists)} artists fully covered)")
    print(f"Partial: {len(partial)}, Missing: {len(missing)}")
    
    if not args.update:
        print(f"\nDRY-RUN MODE (use --update to add missing artists)")
        return
    
    to_add = missing[:args.max_add]
    print(f"\n{'=' * 60}")
    print(f"ADDING {len(to_add)} ARTISTS")
    print(f"{'=' * 60}")
    
    all_new_rows = []
    added_count = 0
    
    for artist in to_add:
        name = artist["artist_name"]
        print(f"\n  {name}...")
        
        try:
            df_rows = add_discovered_artist(
                name, 
                existing_track_ids,
                skip_unknown=False,
                tracks_per_artist=DEFAULT_TRACKS_PER_ARTIST,
                verbose=args.verbose,
                quiet=False,
            )
            
            if df_rows is None or len(df_rows) == 0:
                print(f"    X Not found or no tracks")
                continue
            
            if len(df_rows) < args.min_tracks:
                print(f"    X Only {len(df_rows)} tracks (min: {args.min_tracks})")
                continue
            
            genre = df_rows['genre'][0] if 'genre' in df_rows.columns else 'unknown'
            print(f"    + Added {len(df_rows)} tracks ({genre})")
            
            all_new_rows.append(df_rows)
            added_count += 1
            
            for tid in df_rows['track_id'].drop_nulls().to_list():
                existing_track_ids.add(tid)
            
        except Exception as e:
            print(f"    X Error: {e}")
        
        time.sleep(0.5)
    
    if not all_new_rows:
        print("\nNo artists added")
        return
    
    df_new = pl.concat(all_new_rows)
    df_combined = pl.concat([df_added, df_new])
    df_combined, removed = deduplicate_with_report(df_combined, df_main)
    
    save_parquet(df_combined)
    print(f"\n{'=' * 60}")
    print(f"+ Added {added_count} artists ({len(df_new)} tracks)")
    print(f"+ Total in added_artists.parquet: {len(df_combined)} tracks")
    print(f"\nRun process_data.py to merge with main dataset")


if __name__ == "__main__":
    main()
