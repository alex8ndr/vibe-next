#!/usr/bin/env python3
"""
Add artist tracks to dataset using ReccoBeats API.

Usage:
    # Interactive mode (recommended)
    python add_artist.py
    
    # Single artist by Spotify track ID or URL
    python add_artist.py --track "SPOTIFY_TRACK_ID"
    python add_artist.py --track "https://open.spotify.com/track/xxx"
    
    # Search by artist name (auto-fetches Spotify track via Deezer+ISRC)
    python add_artist.py --names "Radiohead, Coldplay"
    
    # Batch from file (one Spotify track ID per line)
    python add_artist.py --file tracks.txt
    
    # Dry-run: preview changes without saving
    python add_artist.py --track "TRACK_ID" --dry-run
    
    # Update mode: add popular tracks to existing artists
    python add_artist.py --track "TRACK_ID" --update
    
    # Override mode: replace artist's tracks in added_artists.csv.zip
    python add_artist.py --track "TRACK_ID" --override --limit 20
    
Features:
    - Auto-genre detection via TheAudioDB (maps to dataset genres)
    - Artist name search via Deezer → ISRC → ReccoBeats
    - Automatic deduplication by track_id and normalized track name
    - Dry-run mode with optional confirmation to save
    - Interactive mode when run without arguments
    
Output:
    Creates/appends to added_artists.csv.zip (raw format matching data.csv.zip)
    Run process_data.py to merge with main dataset.
"""
import os
import sys
import argparse
import time
import zipfile
import io
import re
from typing import List, Dict, Optional, Tuple

import pandas as pd
import requests

BASE_URL = "https://api.reccobeats.com/v1"
DEEZER_URL = "https://api.deezer.com"
AUDIODB_URL = "https://www.theaudiodb.com/api/v1/json/2"
SONGLINK_URL = "https://api.song.link/v1-alpha.1/links"
MAIN_DATASET = "data.csv.zip"
OUTPUT_CSV = "added_artists.csv.zip"

RAW_COLS = [
    "artist_name", "track_name", "track_id", "popularity", "year", "genre",
    "danceability", "energy", "key", "loudness", "mode", "speechiness",
    "acousticness", "instrumentalness", "liveness", "valence", "tempo",
    "duration_ms", "time_signature"
]

# TheAudioDB genre → dataset genre mapping
AUDIODB_GENRE_MAP = {
    # Rock variants
    'rock': 'rock', 'classic rock': 'rock', 'hard rock': 'hard-rock',
    'alternative rock': 'alt-rock', 'indie rock': 'indie-pop', 'indie': 'indie-pop',
    'psychedelic rock': 'psych-rock', 'progressive rock': 'rock', 'art rock': 'alt-rock',
    'garage rock': 'garage', 'grunge': 'alt-rock', 'post-punk': 'punk-rock',
    
    # Metal
    'metal': 'metal', 'heavy metal': 'heavy-metal', 'thrash metal': 'metal',
    'death metal': 'death-metal', 'black metal': 'black-metal', 'doom metal': 'metal',
    'nu metal': 'metal', 'metalcore': 'metalcore', 'industrial metal': 'industrial',
    'gothic metal': 'goth', 'symphonic metal': 'goth', 'progressive metal': 'metal',
    
    # Punk
    'punk': 'punk', 'punk rock': 'punk-rock', 'pop punk': 'punk', 'hardcore': 'hardcore',
    'post-hardcore': 'hardcore', 'emo': 'emo', 'screamo': 'emo',
    
    # Pop
    'pop': 'pop', 'dance pop': 'dance', 'electropop': 'electro', 'synth-pop': 'electro',
    'teen pop': 'pop', 'bubblegum pop': 'pop', 'power pop': 'power-pop',
    
    # K-Pop / Asian
    'k-pop': 'k-pop', 'j-pop': 'k-pop', 'c-pop': 'cantopop', 'mandopop': 'cantopop',
    
    # Hip-Hop / R&B
    'hip hop': 'hip-hop', 'hip-hop': 'hip-hop', 'rap': 'hip-hop', 'trap': 'hip-hop',
    'r&b': 'soul', 'rnb': 'soul', 'soul': 'soul', 'neo soul': 'soul', 'funk': 'funk',
    'gospel': 'gospel',
    
    # Electronic
    'electronic': 'electronic', 'edm': 'edm', 'house': 'house', 'deep house': 'deep-house',
    'techno': 'techno', 'trance': 'trance', 'dubstep': 'dubstep', 'drum and bass': 'drum-and-bass',
    'ambient': 'ambient', 'downtempo': 'chill', 'chillout': 'chill', 'trip hop': 'trip-hop',
    'industrial': 'industrial', 'electro': 'electro', 'disco': 'disco',
    
    # Acoustic / Folk / Country
    'folk': 'folk', 'acoustic': 'acoustic', 'singer-songwriter': 'singer-songwriter',
    'country': 'country', 'americana': 'country', 'bluegrass': 'folk',
    
    # Jazz / Blues
    'jazz': 'jazz', 'blues': 'blues', 'swing': 'jazz', 'bebop': 'jazz',
    
    # Latin
    'latin': 'salsa', 'salsa': 'salsa', 'reggaeton': 'dancehall', 'bossa nova': 'samba',
    'samba': 'samba', 'tango': 'tango',
    
    # Reggae
    'reggae': 'dancehall', 'ska': 'ska', 'dancehall': 'dancehall', 'dub': 'dub',
    
    # Classical
    'classical': 'classical', 'opera': 'opera', 'orchestral': 'classical',
    'soundtrack': 'pop-film', 'musical': 'show-tunes',
    
    # World
    'world': 'indian', 'indian': 'indian', 'bollywood': 'pop-film',
}


class ReccoBeatsClient:
    """Client for ReccoBeats API."""
    TIMEOUT = 20

    def get_tracks(self, spotify_ids: List[str]) -> List[Dict]:
        """Get track details by Spotify IDs (batch, max ~50)."""
        if not spotify_ids:
            return []
        url = f"{BASE_URL}/track"
        r = requests.get(url, params={"ids": ",".join(spotify_ids)}, timeout=self.TIMEOUT)
        r.raise_for_status()
        return r.json().get("content", [])

    def get_artist(self, recco_uuid: str) -> Dict:
        """Get artist by ReccoBeats UUID."""
        url = f"{BASE_URL}/artist/{recco_uuid}"
        r = requests.get(url, timeout=self.TIMEOUT)
        r.raise_for_status()
        return r.json()

    def get_artist_tracks(self, recco_uuid: str, limit: int = 20) -> List[Dict]:
        """Get artist's most popular tracks by ReccoBeats UUID."""
        fetch_limit = (limit * 3 + 49) // 50 * 50
        tracks = []
        page = 0
        while len(tracks) < fetch_limit:
            url = f"{BASE_URL}/artist/{recco_uuid}/track"
            r = requests.get(url, params={"page": page, "size": 50}, timeout=self.TIMEOUT)
            r.raise_for_status()
            batch = r.json().get("content", [])
            if not batch:
                break
            tracks.extend(batch)
            page += 1
        
        tracks.sort(key=lambda t: t.get("popularity", 0), reverse=True)
        return tracks[:limit]

    def get_audio_features(self, spotify_ids: List[str]) -> Dict[str, Dict]:
        """Get audio features by Spotify track IDs."""
        if not spotify_ids:
            return {}
        features = {}
        for i in range(0, len(spotify_ids), 50):
            batch = spotify_ids[i:i+50]
            url = f"{BASE_URL}/audio-features"
            r = requests.get(url, params={"ids": ",".join(batch)}, timeout=self.TIMEOUT)
            r.raise_for_status()
            for feat in r.json().get("content", []):
                if feat and "href" in feat:
                    sid = feat["href"].split("/")[-1]
                    features[sid] = feat
        return features


def get_genre_from_audiodb(artist_name: str) -> Optional[str]:
    """Fetch artist genre from TheAudioDB and map to dataset genre."""
    try:
        url = f"{AUDIODB_URL}/search.php"
        r = requests.get(url, params={"s": artist_name}, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        artists = data.get("artists")
        if not artists:
            return None
        
        artist = artists[0]
        genre = artist.get("strGenre", "").lower().strip()
        style = artist.get("strStyle", "").lower().strip()
        
        # Try genre first, then style
        for term in [genre, style]:
            if term in AUDIODB_GENRE_MAP:
                return AUDIODB_GENRE_MAP[term]
        
        # Partial match
        for term in [genre, style]:
            for key, value in AUDIODB_GENRE_MAP.items():
                if key in term or term in key:
                    return value
        
        return None
    except Exception:
        return None


def search_artist_via_deezer(artist_name: str, verbose: bool = False) -> Optional[str]:
    """
    Search for artist on Deezer, convert track to Spotify via Songlink.
    Returns Spotify track ID if successful.
    """
    try:
        # Search Deezer for artist
        r = requests.get(f"{DEEZER_URL}/search/artist", params={"q": artist_name, "limit": 1}, timeout=10)
        r.raise_for_status()
        artists = r.json().get("data", [])
        if not artists:
            print(f"    Not found on Deezer")
            return None
        
        deezer_artist = artists[0]
        found_name = deezer_artist["name"]
        print(f"    Found: {found_name}")
        
        # Get top tracks
        r = requests.get(f"{DEEZER_URL}/artist/{deezer_artist['id']}/top", params={"limit": 5}, timeout=10)
        r.raise_for_status()
        tracks = r.json().get("data", [])
        if not tracks:
            print(f"    No tracks on Deezer")
            return None
        
        # Try each track via Songlink
        for track in tracks:
            track_id = track.get("id")
            track_title = track.get("title", "")
            
            if verbose:
                print(f"    Trying: {track_title}")
            
            try:
                # Use Songlink to convert Deezer → Spotify
                deezer_url = f"https://deezer.com/track/{track_id}"
                r = requests.get(SONGLINK_URL, params={"url": deezer_url}, timeout=15)
                
                if r.status_code == 200:
                    data = r.json()
                    spotify_url = data.get("linksByPlatform", {}).get("spotify", {}).get("url")
                    
                    if spotify_url:
                        spotify_id = spotify_url.split("/")[-1].split("?")[0]
                        print(f"    Matched: {track_title}")
                        return spotify_id
            except Exception:
                pass
            
            time.sleep(0.3)
        
        print(f"    Could not find Spotify link")
        return None
        
    except Exception as e:
        print(f"    Search failed: {e}")
        return None


def extract_spotify_id(url_or_id: str) -> str:
    """Extract Spotify ID from URL or return as-is if already an ID."""
    if "spotify.com" in url_or_id:
        return url_or_id.split("/")[-1].split("?")[0]
    return url_or_id


def normalize_track_name(name: str) -> str:
    """Normalize track name for deduplication."""
    if not name or pd.isna(name):
        return ""
    # Lowercase, remove parentheses content, normalize spaces
    normalized = str(name).lower().strip()
    normalized = re.sub(r'\([^)]*\)', '', normalized)  # Remove (remix), (feat. x), etc.
    normalized = re.sub(r'\[[^\]]*\]', '', normalized)  # Remove [explicit], etc.
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def build_rows(artist_name: str, tracks: List[Dict], features: Dict[str, Dict], 
               genre: Optional[str], verbose: bool) -> pd.DataFrame:
    """Build DataFrame from API responses with RAW (unscaled) values."""
    rows = []
    for track in tracks:
        href = track.get("href", "")
        spotify_id = href.split("/")[-1] if href else None
        if not spotify_id:
            continue

        feat = features.get(spotify_id, {})
        
        row = {
            "artist_name": artist_name,
            "track_name": track.get("trackTitle"),
            "track_id": spotify_id,
            "popularity": track.get("popularity"),
            "year": None,
            "genre": genre or "unknown",
            "danceability": feat.get("danceability"),
            "energy": feat.get("energy"),
            "key": feat.get("key"),
            "loudness": feat.get("loudness"),
            "mode": feat.get("mode"),
            "speechiness": feat.get("speechiness"),
            "acousticness": feat.get("acousticness"),
            "instrumentalness": feat.get("instrumentalness"),
            "liveness": feat.get("liveness"),
            "valence": feat.get("valence"),
            "tempo": feat.get("tempo"),
            "duration_ms": track.get("durationMs"),
            "time_signature": feat.get("time_signature"),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    for col in RAW_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[RAW_COLS]
    
    if verbose and not df.empty:
        print(f"\n  Preview ({len(df)} rows):")
        print(df[["track_name", "popularity", "genre", "danceability", "energy"]].head(5).to_string(index=False))
    
    return df


def load_existing() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load both main dataset and added_artists.csv.zip if they exist."""
    df_main = pd.DataFrame(columns=RAW_COLS)
    df_added = pd.DataFrame(columns=RAW_COLS)
    
    if os.path.exists(MAIN_DATASET):
        df_main = pd.read_csv(MAIN_DATASET)
    
    if os.path.exists(OUTPUT_CSV):
        df_added = pd.read_csv(OUTPUT_CSV)
    
    return df_main, df_added


def save_csv_zip(df: pd.DataFrame) -> None:
    """Save DataFrame to compressed CSV zip."""
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    
    with zipfile.ZipFile(OUTPUT_CSV, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("added_artists.csv", csv_buffer.getvalue())


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
    
    artist_tracks = client.get_artist_tracks(artist_uuid, limit)
    if not artist_tracks:
        print(f"  No tracks found")
        return None
    
    spotify_ids = [t.get("href", "").split("/")[-1] for t in artist_tracks if t.get("href")]
    features = client.get_audio_features(spotify_ids)
    
    df_new = build_rows(artist_name, artist_tracks, features, detected_genre, verbose)
    print(f"  Fetched {len(df_new)} tracks")
    
    return df_new, artist_name


def deduplicate_with_report(df_combined: pd.DataFrame, df_main: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """Deduplicate and return removed track names for reporting."""
    removed_tracks = []
    
    # Track IDs already in main dataset
    main_track_ids = set(df_main["track_id"].dropna().unique()) if not df_main.empty else set()
    
    # Deduplicate by track_id
    before = len(df_combined)
    mask_id = df_combined["track_id"].isin(main_track_ids) | df_combined.duplicated(subset=["track_id"], keep="first")
    removed_by_id = df_combined[mask_id][["artist_name", "track_name"]].values.tolist()
    df_combined = df_combined[~mask_id]
    
    for artist, track in removed_by_id:
        removed_tracks.append(f"  - {artist} - {track} (duplicate track_id)")
    
    # Deduplicate by normalized name within same artist
    df_combined["_normalized"] = df_combined["track_name"].apply(normalize_track_name)
    before = len(df_combined)
    mask_name = df_combined.duplicated(subset=["_normalized", "artist_name"], keep="first")
    removed_by_name = df_combined[mask_name][["artist_name", "track_name"]].values.tolist()
    df_combined = df_combined[~mask_name]
    df_combined = df_combined.drop(columns=["_normalized"])
    
    for artist, track in removed_by_name:
        removed_tracks.append(f"  - {artist} - {track} (similar name)")
    
    return df_combined, removed_tracks


def interactive_mode():
    """Run in interactive mode, prompting user for input."""
    print("\n=== Add Artist - Interactive Mode ===\n")
    
    # Get valid genres from AUDIODB_GENRE_MAP values
    valid_genres = sorted(set(AUDIODB_GENRE_MAP.values()))
    
    df_main, df_added = load_existing()
    df_all = pd.concat([df_main, df_added], ignore_index=True)
    print(f"Dataset: {len(df_main)} tracks, {df_main['artist_name'].nunique() if not df_main.empty else 0} artists")
    print(f"Added: {len(df_added)} tracks, {df_added['artist_name'].nunique() if not df_added.empty else 0} artists\n")
    
    while True:
        print("-" * 50)
        user_input = input("\nEnter artist name or Spotify URL (or 'q' to quit): ").strip()
        
        if user_input.lower() in ('q', 'quit', 'exit'):
            print("Goodbye!")
            break
        
        if not user_input:
            continue
        
        # Determine if it's a URL or artist name
        if "spotify.com" in user_input:
            spotify_id = extract_spotify_id(user_input)
            print(f"\nProcessing Spotify track: {spotify_id}")
        else:
            print(f"\nSearching for: {user_input}")
            spotify_id = search_artist_via_deezer(user_input, verbose=True)
            if not spotify_id:
                print("Could not find artist. Try a Spotify URL instead.")
                continue
        
        # Get limit
        limit_input = input("Number of tracks to fetch [20]: ").strip()
        limit = int(limit_input) if limit_input.isdigit() else 20
        
        # Process - fetch tracks without genre first
        client = ReccoBeatsClient()
        existing_artists = set(df_all["artist_name"].dropna().unique())
        
        result = process_single_track(client, spotify_id, limit, None, existing_artists, verbose=False)
        
        if result is None:
            continue
        
        df_new, artist_name = result
        current_genre = df_new["genre"].iloc[0] if not df_new.empty else "unknown"
        
        # Show tracks with numbers for selection
        print(f"\n--- {artist_name} - {len(df_new)} tracks (genre: {current_genre}) ---")
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
            df_all = pd.concat([df_main, df_added], ignore_index=True)
            print(f"\n✓ Saved! Total: {len(df_added)} tracks, {df_added['artist_name'].nunique()} artists")
        else:
            print("Discarded.")


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
    parser = argparse.ArgumentParser(description="Add artists to dataset via ReccoBeats API")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--track", help="Spotify track ID or URL (any song by the artist)")
    group.add_argument("--file", help="File with Spotify track IDs (one per line)")
    group.add_argument("--names", help="Comma-separated artist names (searches via Deezer)")
    group.add_argument("--update-genre", help="Update genres: 'Artist=genre,Artist2=genre2'")
    
    parser.add_argument("--limit", type=int, default=15, help="Max tracks per artist (default: 15)")
    parser.add_argument("--genre", default=None, help="Genre name (auto-detected if not provided)")
    parser.add_argument("--update", action="store_true", help="Update mode: add tracks to existing artists")
    parser.add_argument("--override", action="store_true", help="Override mode: replace artist's tracks")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed info")
    args = parser.parse_args()
    
    # Genre update mode
    if args.update_genre:
        update_genres(args.update_genre)
        return
    
    # Interactive mode if no input specified
    if not args.track and not args.file and not args.names:
        interactive_mode()
        return
    
    # Validate flags
    if args.update and args.override:
        print("Error: Cannot use --update and --override together")
        sys.exit(1)

    # Collect track IDs to process
    track_ids = []
    
    if args.track:
        track_ids.append(extract_spotify_id(args.track))
    
    elif args.file:
        if not os.path.exists(args.file):
            print(f"File not found: {args.file}")
            sys.exit(1)
        with open(args.file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    track_ids.append(extract_spotify_id(line))
        print(f"Loaded {len(track_ids)} track IDs from {args.file}")
    
    elif args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        print(f"Searching for {len(names)} artists via Deezer...\n")
        
        for name in names:
            print(f"  {name}:")
            spotify_id = search_artist_via_deezer(name)
            if spotify_id:
                track_ids.append(spotify_id)
            time.sleep(0.3)
        
        if not track_ids:
            print("\nNo artists found. Try using Spotify URLs instead.")
            sys.exit(1)
        
        print(f"\nFound {len(track_ids)}/{len(names)} artists\n")
    
    if not track_ids:
        print("No track IDs to process")
        sys.exit(1)
    
    # Process each track
    client = ReccoBeatsClient()
    df_main, df_added = load_existing()
    
    df_all_existing = pd.concat([df_main, df_added], ignore_index=True)
    existing_artists = set(df_all_existing["artist_name"].dropna().unique()) if not (args.update or args.override) else set()
    
    print(f"Main dataset: {len(df_main)} tracks, {df_main['artist_name'].nunique() if not df_main.empty else 0} artists")
    print(f"Added artists: {len(df_added)} tracks, {df_added['artist_name'].nunique() if not df_added.empty else 0} artists")
    print(f"Total existing: {len(df_all_existing)} tracks, {df_all_existing['artist_name'].nunique()} artists\n")
    
    if args.dry_run:
        print("DRY-RUN MODE: No changes will be saved\n")
    elif args.update:
        print("Update mode: Will add tracks to existing artists\n")
    elif args.override:
        print("Override mode: Will replace existing tracks in added_artists.csv.zip\n")
    
    artists_to_override = set()
    all_new_rows = []
    
    for i, spotify_id in enumerate(track_ids):
        print(f"[{i+1}/{len(track_ids)}] Processing track: {spotify_id}")
        
        try:
            result = process_single_track(client, spotify_id, args.limit, args.genre, existing_artists, args.verbose)
            if result is not None:
                all_new_rows.append(result[0])
                if args.override and result[1]:
                    artists_to_override.add(result[1])
        except Exception as e:
            print(f"  Error: {e}")
        
        if i < len(track_ids) - 1:
            time.sleep(0.5)
    
    if not all_new_rows:
        print("\nNo new tracks to add")
        return
    
    # Combine all new rows
    df_new = pd.concat(all_new_rows, ignore_index=True)
    print(f"\nTotal new rows: {len(df_new)}")
    
    # Override mode: remove existing tracks for these artists from added_artists
    if args.override and artists_to_override:
        before_override = len(df_added)
        df_added = df_added[~df_added["artist_name"].isin(artists_to_override)]
        removed = before_override - len(df_added)
        if removed:
            print(f"Removed {removed} existing tracks for {len(artists_to_override)} artist(s)")
    
    # Merge with existing added_artists
    df_combined = pd.concat([df_added, df_new], ignore_index=True)
    
    # Deduplicate with detailed reporting
    df_combined, removed_tracks = deduplicate_with_report(df_combined, df_main)
    
    if removed_tracks:
        print(f"\nRemoved {len(removed_tracks)} duplicates:")
        for r in removed_tracks[:10]:
            print(r)
        if len(removed_tracks) > 10:
            print(f"  ... and {len(removed_tracks) - 10} more")
    
    # Dry-run: show preview and optionally save
    if args.dry_run:
        print(f"\n--- DRY-RUN PREVIEW ---")
        print(f"Would save: {len(df_combined)} tracks, {df_combined['artist_name'].nunique()} artists")
        print(f"\nNew tracks by artist:")
        for artist in df_new["artist_name"].unique():
            count = len(df_new[df_new["artist_name"] == artist])
            genre = df_new[df_new["artist_name"] == artist]["genre"].iloc[0]
            print(f"  {artist}: {count} tracks ({genre})")
        
        confirm = input("\nSave these changes? [y/N]: ").strip().lower()
        if confirm not in ('y', 'yes'):
            print("Changes discarded.")
            return
    
    save_csv_zip(df_combined)
    print(f"\n✓ Saved: {len(df_combined)} tracks, {df_combined['artist_name'].nunique()} artists")
    print(f"Output: {OUTPUT_CSV}")
    print(f"\nNext step: Run process_data.py to merge with main dataset")


if __name__ == "__main__":
    main()