#!/usr/bin/env python3
"""
Add artist/album tracks to dataset using ReccoBeats API.

Usage:
    # Interactive mode (recommended) - supports track and album URLs
    python add_artist.py
    
    # Single artist by Spotify track (fetches top tracks)
    python add_artist.py --track "https://open.spotify.com/track/xxx"
    
    # Album: fetch all tracks from an album (efficient for existing artists)
    python add_artist.py --album "https://open.spotify.com/album/xxx"
    
    # Auto-detect from URL (track or album)
    python add_artist.py --url "https://open.spotify.com/album/xxx"
    
    # Batch from file (mix of track/album URLs, auto-detected)
    python add_artist.py --file urls.txt
    
    # Search by artist name
    python add_artist.py --names "Radiohead, Coldplay"
    
    # Dry-run: preview changes without saving
    python add_artist.py --album "ALBUM_ID" --dry-run
    
    # List artists in added_artists.csv.zip
    python add_artist.py --list
    
    # Remove specific artists
    python add_artist.py --remove "Radiohead,Coldplay"
    
    # Clear all added data
    python add_artist.py --remove all
    
    # Add artist + expand to 5 similar artists via Last.fm
    python add_artist.py --names "Radiohead" --expand
    python add_artist.py --names "Radiohead" --expand 10  # expand to 10 similar

Album mode:
    - Efficient for adding new albums to existing artists
    - Skips tracks already in dataset (by track_id)
    - Batches audio features (50 per request)
    - Caches genre lookups per artist
    
Features:
    - Auto-genre detection via TheAudioDB (maps to dataset genres)
    - Artist name search via Deezer → ISRC → ReccoBeats
    - Automatic deduplication by track_id and normalized track name
    - Dry-run mode with optional confirmation to save
    - --expand flag to also add similar artists via Last.fm (requires LASTFM_API_KEY)
    
Output:
    Creates/appends to added_artists.csv.zip (raw format matching data.csv.zip)
    Run process_data.py to merge with main dataset.
"""
import os
import sys
import argparse
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pandas as pd

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from track_dedup import deduplicate_tracks, normalize_track_name
from utils import (
    ReccoBeatsClient,
    LastFmClient,
    get_genre_from_audiodb,
    get_cached_genre,
    search_artist_via_deezer,
    extract_spotify_id,
    build_rows,
    load_existing,
    save_csv_zip,
    deduplicate_with_report,
    add_discovered_artist,
    weighted_track_sample,
    AUDIODB_GENRE_MAP,
    RAW_COLS,
    DEEZER_URL,
    SONGLINK_URL,
    OUTPUT_CSV,
)


def process_single_track(client: ReccoBeatsClient, spotify_id: str, limit: int, 
                         genre: Optional[str], existing_artists: set, 
                         verbose: bool) -> Optional[Tuple[pd.DataFrame, str]]:
    """Process a single track ID and return (new rows DataFrame, artist_name)."""
    tracks = client.get_tracks([spotify_id])
    if not tracks:
        print(f"  Track not found")
        return None
    
    track = tracks[0]
    artists = track.get("artists", [])
    if not artists:
        print(f"  No artist found")
        return None
    
    artist = artists[0]
    artist_uuid = artist["id"]
    artist_name = artist["name"]
    print(f"  Artist: {artist_name}")
    
    if artist_name in existing_artists:
        print(f"  Artist already exists (skipped)")
        return None
    
    # Auto-detect genre if not provided
    detected_genre = genre
    if not detected_genre:
        detected_genre = get_genre_from_audiodb(artist_name)
        if detected_genre:
            print(f"  Genre (auto): {detected_genre}")
        else:
            detected_genre = "unknown"
            print(f"  Genre: unknown (not found in TheAudioDB)")
    
    # Over-fetch to get diverse selection pool
    fetch_limit = limit * 3
    artist_tracks = client.get_artist_tracks(artist_uuid, fetch_limit)
    if not artist_tracks:
        print(f"  No tracks found")
        return None
    
    # Pre-deduplicate tracks before sampling (keep highest popularity per normalized name)
    seen = {}
    for t in artist_tracks:
        key = normalize_track_name(t.get("trackTitle", ""))
        pop = t.get("popularity", 0) or 0
        if key not in seen or pop > seen[key].get("popularity", 0):
            seen[key] = t
    artist_tracks = list(seen.values())
    
    spotify_ids = [t.get("href", "").split("/")[-1] for t in artist_tracks if t.get("href")]
    features = client.get_audio_features(spotify_ids)
    
    # Sample for diversity (popularity + audio feature spread)
    sampled_tracks = weighted_track_sample(artist_tracks, features, target_count=limit)
    
    df_new = build_rows(artist_name, sampled_tracks, features, detected_genre, verbose)
    
    print(f"  Fetched {len(df_new)} tracks")
    
    return df_new, artist_name


def process_album(client: ReccoBeatsClient, spotify_id: str, 
                  genre: Optional[str], existing_track_ids: set,
                  verbose: bool) -> Optional[Tuple[pd.DataFrame, str, str]]:
    """Process an album and return (DataFrame, artist_name, album_name)."""
    album = client.get_album(spotify_id)
    if not album:
        print(f"  Album not found")
        return None
    
    album_uuid = album.get("id")
    album_name = album.get("name", "Unknown Album")
    
    artists = album.get("artists", [])
    if not artists:
        print(f"  No artist found on album")
        return None
    
    artist_name = artists[0].get("name", "Unknown Artist")
    print(f"  Album: {album_name}")
    print(f"  Artist: {artist_name}")
    
    tracks = client.get_album_tracks(album_uuid)
    if not tracks:
        print(f"  No tracks found")
        return None
    
    all_spotify_ids = []
    for t in tracks:
        href = t.get("href", "")
        if href:
            sid = href.split("/")[-1]
            all_spotify_ids.append(sid)
    
    new_spotify_ids = [sid for sid in all_spotify_ids if sid not in existing_track_ids]
    skipped = len(all_spotify_ids) - len(new_spotify_ids)
    if skipped:
        print(f"  Skipping {skipped} existing tracks")
    
    if not new_spotify_ids:
        print(f"  All tracks already in dataset")
        return None
    
    features = client.get_audio_features(new_spotify_ids)
    new_tracks = [t for t in tracks if t.get("href", "").split("/")[-1] in new_spotify_ids]
    
    detected_genre = genre
    if not detected_genre:
        detected_genre = get_cached_genre(artist_name)
        if detected_genre:
            print(f"  Genre (auto): {detected_genre}")
        else:
            detected_genre = "unknown"
            print(f"  Genre: unknown")
    
    df_new = build_rows(artist_name, new_tracks, features, detected_genre, verbose)
    df_new = deduplicate_tracks(df_new, track_col="track_name")
    
    print(f"  Fetched {len(df_new)} tracks")
    
    return df_new, artist_name, album_name


def interactive_mode():
    """Run in interactive mode, prompting user for input."""
    print("\n=== Add Artist/Album - Interactive Mode ===\n")
    
    valid_genres = sorted(set(AUDIODB_GENRE_MAP.values()))
    
    df_main, df_added = load_existing()
    df_all = pd.concat([df_main, df_added], ignore_index=True)
    existing_track_ids = set(df_all["track_id"].dropna().unique())
    existing_artists = set(df_all["artist_name"].dropna().unique())
    
    print(f"Dataset: {len(df_main)} tracks ({df_main['artist_name'].nunique() if not df_main.empty else 0} artists)")
    print(f"Added: {len(df_added)} tracks ({df_added['artist_name'].nunique() if not df_added.empty else 0} artists)\n")
    
    client = ReccoBeatsClient()
    
    while True:
        print("-" * 50)
        user_input = input("\nEnter artist name or Spotify URL (track/album) [q=quit]: ").strip()
        
        if user_input.lower() in ('q', 'quit', 'exit'):
            print("Goodbye!")
            break
        
        if not user_input:
            continue
        
        # Determine type and ID
        if "spotify.com" in user_input:
            spotify_id, item_type = extract_spotify_id(user_input)
            print(f"\nProcessing {item_type}: {spotify_id}")
        else:
            print(f"\nSearching for: {user_input}")
            spotify_id = search_artist_via_deezer(user_input, verbose=True)
            if not spotify_id:
                print("Could not find artist. Try a Spotify URL instead.")
                continue
            item_type = "track"
        
        # Process based on type
        if item_type == "album":
            result = process_album(client, spotify_id, None, existing_track_ids, verbose=False)
            if result is None:
                continue
            df_new, artist_name, album_name = result
            current_genre = df_new["genre"].iloc[0] if not df_new.empty else "unknown"
            print(f"\n--- {artist_name} - {album_name} ({len(df_new)} tracks, {current_genre}) ---")
        else:
            limit_input = input("Number of tracks to fetch [20]: ").strip()
            limit = int(limit_input) if limit_input.isdigit() else 20
            
            result = process_single_track(client, spotify_id, limit, None, existing_artists, verbose=False)
            if result is None:
                continue
            df_new, artist_name = result
            current_genre = df_new["genre"].iloc[0] if not df_new.empty else "unknown"
            print(f"\n--- {artist_name} ({len(df_new)} tracks, {current_genre}) ---")
        
        # Show tracks with numbers for selection
        for i, row in df_new.iterrows():
            print(f"  {i+1:2}. {row['track_name'][:50]:<50} pop:{row['popularity']:>3}")
        
        # Genre override
        genre_input = input(f"\nGenre [{current_genre}] (or '?' for list): ").strip().lower()
        if genre_input == '?':
            print("\nValid genres:")
            for i, g in enumerate(valid_genres):
                print(f"  {g}", end="  " if (i + 1) % 6 else "\n")
            print()
            genre_input = input(f"Genre [{current_genre}]: ").strip().lower()
        
        if genre_input:
            if genre_input in valid_genres:
                df_new["genre"] = genre_input
                current_genre = genre_input
            else:
                # Try partial match
                matches = [g for g in valid_genres if genre_input in g]
                if len(matches) == 1:
                    df_new["genre"] = matches[0]
                    current_genre = matches[0]
                    print(f"  → Using: {matches[0]}")
                elif matches:
                    print(f"  Multiple matches: {', '.join(matches)}")
                    print(f"  Keeping: {current_genre}")
                else:
                    print(f"  Unknown genre '{genre_input}', keeping: {current_genre}")
        
        # Track selection
        track_input = input(f"\nTracks to add [all] (e.g. '1-5' or '1,3,5,7'): ").strip()
        if track_input:
            try:
                selected_indices = []
                for part in track_input.replace(" ", "").split(","):
                    if "-" in part:
                        start, end = part.split("-")
                        selected_indices.extend(range(int(start)-1, int(end)))
                    else:
                        selected_indices.append(int(part) - 1)
                
                # Filter to valid indices
                selected_indices = [i for i in selected_indices if 0 <= i < len(df_new)]
                if selected_indices:
                    df_new = df_new.iloc[selected_indices].reset_index(drop=True)
                    print(f"  Selected {len(df_new)} tracks")
            except ValueError:
                print("  Invalid selection, using all tracks")
        
        # Final preview
        print(f"\n--- Final: {artist_name} ({len(df_new)} tracks, {current_genre}) ---")
        for _, row in df_new.head(10).iterrows():
            print(f"  • {row['track_name'][:55]}")
        if len(df_new) > 10:
            print(f"  ... and {len(df_new) - 10} more")
        
        # Confirm
        confirm = input("\nSave? [Y/n]: ").strip().lower()
        if confirm in ('', 'y', 'yes'):
            df_combined = pd.concat([df_added, df_new], ignore_index=True)
            df_combined, removed = deduplicate_with_report(df_combined, df_main)
            
            if removed:
                print(f"\nRemoved {len(removed)} duplicates:")
                for r in removed[:5]:
                    print(r)
                if len(removed) > 5:
                    print(f"  ... and {len(removed) - 5} more")
            
            save_csv_zip(df_combined)
            df_added = df_combined
            # Update caches for next iteration
            existing_track_ids.update(df_new["track_id"].tolist())
            existing_artists.add(artist_name)
            print(f"\n✓ Saved! Total: {len(df_added)} tracks ({df_added['artist_name'].nunique()} artists)")
        else:
            print("Discarded.")


def list_artists() -> None:
    """List all artists in added_artists.csv.zip."""
    if not os.path.exists(OUTPUT_CSV):
        print(f"No {OUTPUT_CSV} file found")
        return
    
    df = pd.read_csv(OUTPUT_CSV)
    if df.empty:
        print("No artists in added_artists.csv.zip")
        return
    
    grouped = df.groupby('artist_name').agg(
        tracks=('track_id', 'count'),
        genre=('genre', 'first')
    ).sort_values('tracks', ascending=False)
    
    print(f"\nArtists in {OUTPUT_CSV} ({len(grouped)} artists, {len(df)} tracks):\n")
    for artist, row in grouped.iterrows():
        print(f"  {artist}: {row['tracks']} tracks ({row['genre']})")


def remove_artists(artists_arg: str) -> None:
    """Remove artist(s) from added_artists.csv.zip.
    
    Args:
        artists_arg: Comma-separated artist names, or 'all' to clear
    """
    if not os.path.exists(OUTPUT_CSV):
        print(f"No {OUTPUT_CSV} file found")
        return
    
    df = pd.read_csv(OUTPUT_CSV)
    if df.empty:
        print("File is already empty")
        return
    
    if artists_arg.strip().lower() == 'all':
        confirm = input(f"Remove ALL {len(df)} tracks from {OUTPUT_CSV}? [y/N]: ").strip().lower()
        if confirm in ('y', 'yes'):
            os.remove(OUTPUT_CSV)
            print(f"✓ Deleted {OUTPUT_CSV}")
        else:
            print("Cancelled")
        return
    
    artists_to_remove = [a.strip() for a in artists_arg.split(',') if a.strip()]
    if not artists_to_remove:
        print("No artists specified")
        return
    
    print(f"\nRemoving from {OUTPUT_CSV}:")
    total_removed = 0
    
    for artist in artists_to_remove:
        mask = df['artist_name'] == artist
        count = mask.sum()
        if count == 0:
            print(f"  {artist}: Not found")
        else:
            df = df[~mask]
            print(f"  {artist}: Removed {count} tracks")
            total_removed += count
    
    if total_removed > 0:
        if df.empty:
            os.remove(OUTPUT_CSV)
            print(f"\n✓ Removed {total_removed} tracks (file deleted, was empty)")
        else:
            save_csv_zip(df)
            print(f"\n✓ Removed {total_removed} tracks, {len(df)} remaining")
    else:
        print("\nNo changes made")


def expand_from_artists(
    seed_artists: list,
    existing_track_ids: set,
    existing_artists: set,
    df_added: pd.DataFrame,
    df_main: pd.DataFrame,
    limit: int = 5,
    tracks_per_artist: int = 15,
    verbose: bool = False,
) -> pd.DataFrame:
    """Find and add similar artists via Last.fm."""
    lastfm = LastFmClient()
    if not lastfm.api_key:
        print("\nWarning: LASTFM_API_KEY not set, skipping expansion")
        print("Get a free API key at: https://www.last.fm/api/account/create")
        return df_added
    
    print(f"\n{'=' * 50}")
    print(f"EXPANDING: Finding artists similar to {', '.join(seed_artists[:3])}" + 
          ("..." if len(seed_artists) > 3 else ""))
    print(f"{'=' * 50}")
    
    candidates = lastfm.expand_artist_pool(
        seed_artists,
        existing_artists,
        limit=limit * 2,
        min_match=0.4,
    )
    
    if not candidates:
        print("No similar artists found")
        return df_added
    
    print(f"\nFound {len(candidates)} candidates, adding top {limit}:")
    
    all_new_rows = []
    added_count = 0
    skipped_genre = 0
    
    for candidate in candidates[:limit]:
        name = candidate["name"]
        print(f"\n  {name} (match: {candidate['match']:.2f})...")
        
        df_new = add_discovered_artist(
            name,
            existing_track_ids,
            skip_unknown=True,
            tracks_per_artist=tracks_per_artist,
            verbose=verbose,
            quiet=True,
        )
        
        if df_new is None:
            skipped_genre += 1
            print(f"    Skipped (unknown genre or not found)")
            continue
        
        if df_new.empty:
            continue
        
        genre = df_new["genre"].iloc[0]
        print(f"    + Added {len(df_new)} tracks ({genre})")
        all_new_rows.append(df_new)
        added_count += 1
        
        for tid in df_new["track_id"].dropna():
            existing_track_ids.add(tid)
        existing_artists.add(name)
        
        time.sleep(0.5)
    
    if not all_new_rows:
        print("\nNo similar artists added")
        if skipped_genre > 0:
            print(f"  ({skipped_genre} skipped due to unknown genre)")
        return df_added
    
    df_expanded = pd.concat(all_new_rows, ignore_index=True)
    df_combined = pd.concat([df_added, df_expanded], ignore_index=True)
    df_combined, _ = deduplicate_with_report(df_combined, df_main)
    
    print(f"\n+ Expanded: {added_count} artists ({len(df_expanded)} tracks)")
    
    return df_combined


def update_genres(genre_updates: str) -> None:
    """Update genres for artists in added_artists.csv.zip.
    
    Args:
        genre_updates: Format "Artist=genre,Artist2=genre2"
    """
    if not os.path.exists(OUTPUT_CSV):
        print(f"Error: {OUTPUT_CSV} not found")
        sys.exit(1)
    
    # Load data
    df = pd.read_csv(OUTPUT_CSV)
    
    # Get valid genres
    valid_genres = sorted(set(AUDIODB_GENRE_MAP.values()))
    
    # Parse updates
    updates = {}
    for part in genre_updates.split(','):
        if '=' not in part:
            print(f"Warning: Invalid format '{part}', expected 'Artist=genre'")
            continue
        artist, genre = part.split('=', 1)
        artist = artist.strip()
        genre = genre.strip().lower()
        
        # Validate genre
        if genre not in valid_genres:
            # Try partial match
            matches = [g for g in valid_genres if genre in g]
            if len(matches) == 1:
                genre = matches[0]
                print(f"  {artist}: '{genre}' → '{matches[0]}'")
            elif matches:
                print(f"  {artist}: Ambiguous genre '{genre}', matches: {', '.join(matches)}")
                continue
            else:
                print(f"  {artist}: Unknown genre '{genre}', skipping")
                continue
        
        updates[artist] = genre
    
    if not updates:
        print("No valid updates to apply")
        return
    
    # Apply updates
    print(f"\nUpdating {len(updates)} artist(s) in {OUTPUT_CSV}:")
    updated_count = 0
    
    for artist, genre in updates.items():
        mask = df['artist_name'] == artist
        count = mask.sum()
        
        if count == 0:
            print(f"  {artist}: Not found")
        else:
            old_genre = df.loc[mask, 'genre'].iloc[0]
            df.loc[mask, 'genre'] = genre
            print(f"  {artist}: {old_genre} → {genre} ({count} tracks)")
            updated_count += count
    
    if updated_count > 0:
        save_csv_zip(df)
        print(f"\n✓ Updated {updated_count} tracks")
    else:
        print("\nNo changes made")


def main():
    parser = argparse.ArgumentParser(description="Add artists/albums to dataset via ReccoBeats API")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--track", help="Spotify track ID or URL (fetches artist's top tracks)")
    group.add_argument("--album", help="Spotify album ID or URL (fetches all album tracks)")
    group.add_argument("--url", help="Spotify URL (auto-detects track or album)")
    group.add_argument("--file", help="File with Spotify URLs/IDs (one per line)")
    group.add_argument("--names", help="Comma-separated artist names (searches via Deezer)")
    group.add_argument("--update-genre", help="Update genres: 'Artist=genre,Artist2=genre2'")
    group.add_argument("--remove", help="Remove artist(s): 'Artist1,Artist2' or 'all'")
    group.add_argument("--list", action="store_true", help="List artists in added_artists.csv.zip")
    
    parser.add_argument("--limit", type=int, default=15, help="Max tracks per artist (default: 15, ignored for albums)")
    parser.add_argument("--genre", default=None, help="Genre name (auto-detected if not provided)")
    parser.add_argument("--expand", type=int, nargs="?", const=5, default=0, 
                        help="Also add N similar artists via Last.fm (default: 5, requires LASTFM_API_KEY)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed info")
    args = parser.parse_args()
    
    # Genre update mode
    if args.update_genre:
        update_genres(args.update_genre)
        return
    
    # Remove mode
    if args.remove:
        remove_artists(args.remove)
        return
    
    # List mode
    if args.list:
        list_artists()
        return
    
    # Interactive mode if no input specified
    if not args.track and not args.album and not args.url and not args.file and not args.names:
        interactive_mode()
        return

    # Collect items to process: list of (spotify_id, type)
    items: List[Tuple[str, str]] = []
    
    if args.track:
        sid, _ = extract_spotify_id(args.track)
        items.append((sid, "track"))
    
    elif args.album:
        sid, _ = extract_spotify_id(args.album)
        items.append((sid, "album"))
    
    elif args.url:
        items.append(extract_spotify_id(args.url))
    
    elif args.file:
        if not os.path.exists(args.file):
            print(f"File not found: {args.file}")
            sys.exit(1)
        with open(args.file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    items.append(extract_spotify_id(line))
        print(f"Loaded {len(items)} items from {args.file}")
    
    elif args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        print(f"Searching for {len(names)} artists via Deezer...\n")
        
        for name in names:
            print(f"  {name}:")
            spotify_id = search_artist_via_deezer(name)
            if spotify_id:
                items.append((spotify_id, "track"))
            time.sleep(0.3)
        
        if not items:
            print("\nNo artists found. Try using Spotify URLs instead.")
            sys.exit(1)
        
        print(f"\nFound {len(items)}/{len(names)} artists\n")
    
    if not items:
        print("No items to process")
        sys.exit(1)
    
    # Load existing data
    client = ReccoBeatsClient()
    df_main, df_added = load_existing()
    df_all = pd.concat([df_main, df_added], ignore_index=True)
    
    existing_track_ids = set(df_all["track_id"].dropna().unique())
    existing_artists = set(df_all["artist_name"].dropna().unique())
    
    print(f"Dataset: {len(df_main)} tracks ({df_main['artist_name'].nunique() if not df_main.empty else 0} artists)")
    print(f"Added: {len(df_added)} tracks ({df_added['artist_name'].nunique() if not df_added.empty else 0} artists)\n")
    
    if args.dry_run:
        print("DRY-RUN MODE: No changes will be saved\n")
    
    all_new_rows = []
    
    for i, (spotify_id, item_type) in enumerate(items):
        print(f"[{i+1}/{len(items)}] Processing {item_type}: {spotify_id}")
        
        try:
            if item_type == "album":
                result = process_album(client, spotify_id, args.genre, existing_track_ids, args.verbose)
                if result:
                    df_rows, artist_name, album_name = result
                    all_new_rows.append(df_rows)
                    # Update existing_track_ids for subsequent albums
                    existing_track_ids.update(df_rows["track_id"].tolist())
            else:
                result = process_single_track(client, spotify_id, args.limit, args.genre, existing_artists, args.verbose)
                if result:
                    df_rows, artist_name = result
                    all_new_rows.append(df_rows)
                    existing_artists.add(artist_name)
        except Exception as e:
            print(f"  Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
        
        if i < len(items) - 1:
            time.sleep(0.3)
    
    if not all_new_rows:
        print("\nNo new tracks to add")
        return
    
    # Combine and deduplicate
    df_new = pd.concat(all_new_rows, ignore_index=True)
    df_combined = pd.concat([df_added, df_new], ignore_index=True)
    df_combined, removed_tracks = deduplicate_with_report(df_combined, df_main)
    
    print(f"\nTotal new: {len(df_new)} tracks")
    
    if removed_tracks:
        print(f"Removed {len(removed_tracks)} duplicates:")
        for r in removed_tracks[:5]:
            print(r)
        if len(removed_tracks) > 5:
            print(f"  ... and {len(removed_tracks) - 5} more")
    
    # Dry-run preview
    if args.dry_run:
        print(f"\n--- DRY-RUN PREVIEW ---")
        print(f"Would save: {len(df_combined)} tracks ({df_combined['artist_name'].nunique()} artists)")
        print(f"\nNew tracks by artist:")
        for artist in df_new["artist_name"].unique():
            count = len(df_new[df_new["artist_name"] == artist])
            genre = df_new[df_new["artist_name"] == artist]["genre"].iloc[0]
            print(f"  {artist}: {count} tracks ({genre})")
        
        confirm = input("\nSave these changes? [y/N]: ").strip().lower()
        if confirm not in ('y', 'yes'):
            print("Discarded.")
            return
    
    save_csv_zip(df_combined)
    print(f"\n✓ Saved: {len(df_combined)} tracks ({df_combined['artist_name'].nunique()} artists)")
    
    # Expand to similar artists if requested
    if args.expand and not args.dry_run:
        added_artists = list(df_new["artist_name"].unique())
        df_combined = expand_from_artists(
            seed_artists=added_artists,
            existing_track_ids=existing_track_ids,
            existing_artists=existing_artists,
            df_added=df_combined,
            df_main=df_main,
            limit=args.expand,
            tracks_per_artist=args.limit,
            verbose=args.verbose,
        )
        save_csv_zip(df_combined)
        print(f"\n✓ Final: {len(df_combined)} tracks ({df_combined['artist_name'].nunique()} artists)")
    
    print(f"\nRun process_data.py to merge with main dataset")


if __name__ == "__main__":
    main()