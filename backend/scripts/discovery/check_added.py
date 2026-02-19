#!/usr/bin/env python3
"""
Manage the added_artists.parquet dataset.

Usage:
    # List all added artists with track counts and genres
    python check_added.py --list
    
    # List with track names
    python check_added.py --list --tracks
    
    # List all tracks for a specific artist
    python check_added.py --list-tracks "Radiohead"
    
    # Delete artist(s) from added_artists.parquet
    python check_added.py --delete "Radiohead"
    python check_added.py --delete "Radiohead,Coldplay"
    python check_added.py --delete all
    
    # Reclassify artist's genre
    python check_added.py --reclassify "Radiohead=alt-rock"
    
    # Re-fetch genre from TheAudioDB
    python check_added.py --reclassify "Radiohead=api"
    
    # Multiple reclassifications
    python check_added.py --reclassify "Radiohead=alt-rock,Coldplay=pop"

Operations:
    --list          Show artists with track counts and genres
    --list-tracks   Show all tracks for a specific artist (with popularity and main dataset presence)
    --delete        Remove artist(s) from added_artists.parquet only
    --reclassify    Change artist's genre (use 'api' to re-fetch from TheAudioDB)
"""
import sys
import argparse
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent.parent))

from track_dedup import normalize_artist_name
from utils import (
    OUTPUT_PARQUET,
    MAIN_DATASET,
    load_existing,
    save_parquet,
    get_genre_from_audiodb,
    AUDIODB_GENRE_MAP,
)


def list_artists(show_tracks: bool = False) -> None:
    """List all artists in added_artists.parquet."""
    if not OUTPUT_PARQUET.exists():
        print(f"No {OUTPUT_PARQUET} file found")
        return
    
    df = pl.read_parquet(OUTPUT_PARQUET)
    if len(df) == 0:
        print("No artists in added_artists.parquet")
        return
    
    grouped = df.group_by('artist_name').agg(
        pl.col('track_id').count().alias('tracks'),
        pl.col('genre').first().alias('genre')
    ).sort('tracks', descending=True)
    
    print(f"\nArtists in {OUTPUT_PARQUET} ({len(grouped)} artists, {len(df)} tracks):\n")
    
    for row in grouped.iter_rows(named=True):
        print(f"  {row['artist_name']}: {row['tracks']} tracks ({row['genre']})")
        
        if show_tracks:
            artist_tracks = df.filter(pl.col('artist_name') == row['artist_name']).sort('popularity', descending=True)
            for track_row in artist_tracks.iter_rows(named=True):
                track_name = track_row.get('track_name', 'Unknown')
                popularity = track_row.get('popularity', 0) or 0
                print(f"      • {track_name} (pop: {popularity:.0f})")


def list_tracks_for_artist(artist_name: str) -> None:
    """List all tracks for a specific artist in added_artists.parquet."""
    if not OUTPUT_PARQUET.exists():
        print(f"No {OUTPUT_PARQUET} file found")
        return
    
    df = pl.read_parquet(OUTPUT_PARQUET)
    if len(df) == 0:
        print("No artists in added_artists.parquet")
        return
    
    artist_df = df.filter(pl.col('artist_name') == artist_name)
    if len(artist_df) == 0:
        norm_input = normalize_artist_name(artist_name)
        for name in df['artist_name'].unique().to_list():
            if normalize_artist_name(name) == norm_input:
                artist_df = df.filter(pl.col('artist_name') == name)
                artist_name = name
                break
    
    if len(artist_df) == 0:
        print(f"Artist '{artist_name}' not found in added_artists.parquet")
        available = df['artist_name'].unique().sort().to_list()[:10]
        if available:
            print(f"Available artists: {', '.join(available)}")
        return
    
    main_track_ids = set()
    if MAIN_DATASET.exists():
        df_main = pl.read_parquet(MAIN_DATASET)
        main_track_ids = set(df_main['track_id'].drop_nulls().unique().to_list())
    
    artist_df = artist_df.sort('popularity', descending=True)
    genre = artist_df['genre'][0]
    
    print(f"\nTracks for '{artist_name}' ({len(artist_df)} tracks, genre: {genre}):\n")
    
    for row in artist_df.iter_rows(named=True):
        track_name = row.get('track_name', 'Unknown')
        popularity = row.get('popularity', 0) or 0
        track_id = row.get('track_id', '')
        
        in_main = "✓ in main" if track_id in main_track_ids else ""
        print(f"  {track_name:<50} pop: {popularity:>3.0f}  {in_main}")


def delete_artists(artists_arg: str) -> None:
    """Remove artist(s) from added_artists.parquet."""
    if not OUTPUT_PARQUET.exists():
        print(f"No {OUTPUT_PARQUET} file found")
        return
    
    df = pl.read_parquet(OUTPUT_PARQUET)
    if len(df) == 0:
        print("File is already empty")
        return
    
    if artists_arg.strip().lower() == 'all':
        confirm = input(f"Remove ALL {len(df)} tracks from {OUTPUT_PARQUET}? [y/N]: ").strip().lower()
        if confirm in ('y', 'yes'):
            OUTPUT_PARQUET.unlink()
            print(f"✓ Deleted {OUTPUT_PARQUET}")
        else:
            print("Cancelled")
        return
    
    artists_to_remove = [a.strip() for a in artists_arg.split(',') if a.strip()]
    if not artists_to_remove:
        print("No artists specified")
        return
    
    print(f"\nRemoving from {OUTPUT_PARQUET}:")
    total_removed = 0
    
    for artist in artists_to_remove:
        mask = df['artist_name'] == artist
        count = mask.sum()
        if count == 0:
            norm_input = normalize_artist_name(artist)
            for name in df['artist_name'].unique().to_list():
                if normalize_artist_name(name) == norm_input:
                    mask = df['artist_name'] == name
                    count = mask.sum()
                    artist = name
                    break
        
        if count == 0:
            print(f"  {artist}: Not found")
        else:
            df = df.filter(~mask)
            print(f"  {artist}: Removed {count} tracks")
            total_removed += count
    
    if total_removed > 0:
        if len(df) == 0:
            OUTPUT_PARQUET.unlink()
            print(f"\n✓ Removed {total_removed} tracks (file deleted, was empty)")
        else:
            save_parquet(df)
            print(f"\n✓ Removed {total_removed} tracks, {len(df)} remaining")
    else:
        print("\nNo changes made")


def reclassify_artists(genre_updates: str) -> None:
    """Update genres for artists in added_artists.parquet."""
    if not OUTPUT_PARQUET.exists():
        print(f"Error: {OUTPUT_PARQUET} not found")
        sys.exit(1)
    
    df = pl.read_parquet(OUTPUT_PARQUET)
    valid_genres = sorted(set(AUDIODB_GENRE_MAP.values()))
    
    updates = {}
    api_lookups = []
    
    for part in genre_updates.split(','):
        if '=' not in part:
            print(f"Warning: Invalid format '{part}', expected 'Artist=genre'")
            continue
        artist, genre = part.split('=', 1)
        artist = artist.strip()
        genre = genre.strip().lower()
        
        if genre == 'api':
            api_lookups.append(artist)
            continue
        
        if genre not in valid_genres:
            matches = [g for g in valid_genres if genre in g]
            if len(matches) == 1:
                genre = matches[0]
            elif matches:
                print(f"  {artist}: Ambiguous genre '{genre}', matches: {', '.join(matches)}")
                continue
            else:
                print(f"  {artist}: Unknown genre '{genre}', skipping")
                continue
        
        updates[artist] = genre
    
    for artist in api_lookups:
        actual_artist = artist
        mask = df['artist_name'] == artist
        if mask.sum() == 0:
            norm_input = normalize_artist_name(artist)
            for name in df['artist_name'].unique().to_list():
                if normalize_artist_name(name) == norm_input:
                    actual_artist = name
                    break
        
        print(f"  {actual_artist}: Looking up genre via TheAudioDB...")
        genre = get_genre_from_audiodb(actual_artist)
        if genre:
            print(f"  {actual_artist}: Found genre '{genre}'")
            updates[actual_artist] = genre
        else:
            print(f"  {actual_artist}: No genre found in TheAudioDB")
    
    if not updates:
        print("No valid updates to apply")
        return
    
    print(f"\nUpdating {len(updates)} artist(s) in {OUTPUT_PARQUET}:")
    updated_count = 0
    
    for artist, genre in updates.items():
        actual_artist = artist
        mask = df['artist_name'] == artist
        count = mask.sum()
        
        if count == 0:
            norm_input = normalize_artist_name(artist)
            for name in df['artist_name'].unique().to_list():
                if normalize_artist_name(name) == norm_input:
                    actual_artist = name
                    mask = df['artist_name'] == actual_artist
                    count = mask.sum()
                    break
        
        if count == 0:
            print(f"  {artist}: Not found")
        else:
            old_genre = df.filter(mask)["genre"][0]
            df = df.with_columns(
                pl.when(pl.col("artist_name") == actual_artist)
                .then(pl.lit(genre))
                .otherwise(pl.col("genre"))
                .alias("genre")
            )
            print(f"  {actual_artist}: {old_genre} → {genre} ({count} tracks)")
            updated_count += count
    
    if updated_count > 0:
        save_parquet(df)
        print(f"\n✓ Updated {updated_count} tracks")
    else:
        print("\nNo changes made")


def main():
    parser = argparse.ArgumentParser(description="Manage added_artists.parquet dataset")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List artists with track counts and genres")
    group.add_argument("--list-tracks", metavar="ARTIST", help="List all tracks for a specific artist")
    group.add_argument("--delete", metavar="ARTISTS", help="Remove artist(s): 'Artist1,Artist2' or 'all'")
    group.add_argument("--reclassify", metavar="ARTIST=GENRE", help="Change genre: 'Artist=genre' or 'Artist=api' to re-fetch")
    
    parser.add_argument("--tracks", action="store_true", help="With --list, also show track names")
    
    args = parser.parse_args()
    
    if args.list:
        list_artists(show_tracks=args.tracks)
    elif args.list_tracks:
        list_tracks_for_artist(args.list_tracks)
    elif args.delete:
        delete_artists(args.delete)
    elif args.reclassify:
        reclassify_artists(args.reclassify)


if __name__ == "__main__":
    main()
