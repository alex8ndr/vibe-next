#!/usr/bin/env python3
"""
Test genre detection for artists.

Shows:
1. Current dataset genre (if exists)
2. TheAudioDB API raw response and mapped genre
3. Last.fm tags and mapped genre (requires LASTFM_API_KEY)
4. Genre reassignment (if configured)
5. Final genre vector families (if valid)

Usage:
    python test_artist_genre.py "Artist Name" ["Artist 2"] ...
    
    # List all valid dataset genres
    python test_artist_genre.py --list-genres
    
    # Show unmapped TheAudioDB/Last.fm tags (for improving AUDIODB_GENRE_MAP)
    python test_artist_genre.py --check-mapping "Artist Name"
    
    # Test Last.fm similar artist discovery
    python test_artist_genre.py --similar "Artist 1" ["Artist 2"] ...
"""
import sys
import os
import polars as pl
import urllib.parse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    get_genre_from_audiodb,
    get_genre_from_lastfm,
    LastFmClient,
    AUDIODB_GENRE_MAP,
)

# --- CONFIG ---
DATA_PATH = Path("backend/data/data_encoded.parquet")
REASSIGNMENT_DIR = Path("backend/data/reassignments")
# --------------


def load_reassignments():
    """Maps artist_name -> target_genre based on text files."""
    mapping = {}
    if not REASSIGNMENT_DIR.exists():
        return mapping
        
    for fpath in REASSIGNMENT_DIR.glob("*.txt"):
        target_genre = fpath.stem
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    mapping[s.lower()] = target_genre
    return mapping


def get_valid_genres():
    """Get all valid dataset genres from genre_families.py."""
    try:
        from genre_families import GENRE_DEFINITIONS
        return sorted(GENRE_DEFINITIONS.keys())
    except ImportError:
        return sorted(set(AUDIODB_GENRE_MAP.values()))


def check_dataset(artist_name, df):
    """Checks exact matches in the encoded parquet."""
    print("\n1. CURRENT IN DATASET:")
    subset = df.filter(pl.col("artist_name").cast(pl.String).str.to_lowercase() == artist_name.lower())
    
    if subset.height == 0:
        print("   NOT FOUND")
        return None
    else:
        counts = subset.group_by("genre").len().sort("len", descending=True)
        for row in counts.iter_rows(named=True):
            print(f"   {row['genre']}: {row['len']} track(s)")
        return subset


def check_audiodb(artist_name):
    """Queries TheAudioDB for genre."""
    print("\n2. THEAUDIODB API:")
    
    mapped, raw_genre, raw_style = get_genre_from_audiodb(artist_name)
    
    if raw_genre or raw_style:
        print(f"   Raw: genre='{raw_genre}', style='{raw_style}'")
        if mapped:
            print(f"   Mapped -> {mapped}")
        else:
            print(f"   Mapped -> NONE (not in AUDIODB_GENRE_MAP)")
    else:
        print("   Artist not found in TheAudioDB")
    
    return mapped


def check_lastfm(artist_name, lastfm_client):
    """Queries Last.fm for tags."""
    print("\n3. LAST.FM TAGS:")
    
    if not lastfm_client.api_key:
        print("   (LASTFM_API_KEY not set)")
        return None
    
    mapped, raw_tags = get_genre_from_lastfm(artist_name, lastfm_client)
    
    if raw_tags:
        print(f"   Raw tags: {', '.join(raw_tags[:8])}")
        if mapped:
            print(f"   Mapped -> {mapped}")
        else:
            print(f"   Mapped -> NONE (no tags in AUDIODB_GENRE_MAP)")
    else:
        print("   No tags found")
    
    return mapped


def check_reassignment(artist_name, mapping):
    """Checks if a manual override exists."""
    print("\n4. GENRE REASSIGNMENT:")
    target = mapping.get(artist_name.lower())
    if target:
        print(f"   Configured -> {target}")
    else:
        print("   None configured")
    return target


def show_final_genre(artist_name, reassignment, audiodb_genre, lastfm_genre, dataset_rows):
    """Shows what genre will be used and its vector families."""
    print("\n5. FINAL RESULT:")
    
    # Priority: reassignment > dataset > lastfm > audiodb
    final_genre = None
    source = None
    
    if reassignment:
        final_genre = reassignment
        source = "reassignment"
    elif dataset_rows is not None and dataset_rows.height > 0:
        final_genre = dataset_rows.group_by("genre").len().sort("len", descending=True).row(0)[0]
        source = "dataset"
    elif lastfm_genre:
        final_genre = lastfm_genre
        source = "last.fm"
    elif audiodb_genre:
        final_genre = audiodb_genre
        source = "audiodb"
    
    if final_genre:
        print(f"   Genre: {final_genre} (from {source})")
        
        try:
            from genre_families import GENRE_DEFINITIONS
            if final_genre in GENRE_DEFINITIONS:
                dims = GENRE_DEFINITIONS[final_genre]
                print(f"   Vector families ({len(dims)} dimensions):")
                for k, v in dims.items():
                    print(f"     - {k}: {v}")
            else:
                print(f"   WARNING: Genre '{final_genre}' not in GENRE_DEFINITIONS!")
                print(f"   Valid genres: {', '.join(sorted(GENRE_DEFINITIONS.keys())[:20])}...")
        except ImportError:
            print("   (Could not load genre_families.py)")
    else:
        print("   WARNING: NO GENRE DETECTED")
        print("   Options:")
        print("     1. Add to reassignments/<genre>.txt")
        print("     2. Add mapping to AUDIODB_GENRE_MAP in utils.py")


def list_all_genres():
    """Print all valid dataset genres."""
    print("\n=== VALID DATASET GENRES ===\n")
    
    try:
        from genre_families import GENRE_DEFINITIONS
        genres = sorted(GENRE_DEFINITIONS.keys())
        
        # Group by category (rough heuristic based on name)
        categories = {}
        for g in genres:
            if 'metal' in g or g in ['goth', 'grindcore']:
                cat = 'Metal'
            elif 'punk' in g or g in ['emo', 'hardcore', 'grunge']:
                cat = 'Punk/Emo'
            elif 'rock' in g or g in ['garage', 'psych-rock']:
                cat = 'Rock'
            elif 'pop' in g and 'k-' not in g and 'j-' not in g:
                cat = 'Pop'
            elif 'hip' in g or g in ['soul', 'funk', 'gospel']:
                cat = 'Hip-Hop/R&B'
            elif 'electro' in g or g in ['house', 'techno', 'trance', 'dubstep', 'edm', 'ambient', 'chill', 'disco', 'breakbeat']:
                cat = 'Electronic'
            elif 'folk' in g or g in ['acoustic', 'country', 'singer-songwriter', 'songwriter']:
                cat = 'Acoustic/Folk'
            elif 'jazz' in g or 'blues' in g:
                cat = 'Jazz/Blues'
            elif any(x in g for x in ['latin', 'salsa', 'samba', 'tango', 'forro', 'sertanejo', 'afrobeat']):
                cat = 'Latin/World'
            elif g in ['reggae', 'ska', 'dancehall', 'dub']:
                cat = 'Reggae'
            elif 'classical' in g or g in ['opera', 'piano', 'show-tunes', 'pop-film']:
                cat = 'Classical/Cinematic'
            elif any(x in g for x in ['k-pop', 'j-pop', 'j-rock', 'cantopop', 'japanese']):
                cat = 'Asian Pop'
            elif 'christian' in g or g in ['ccm', 'gospel']:
                cat = 'Christian'
            elif any(x in g for x in ['german', 'french', 'spanish', 'swedish', 'indian', 'romance']):
                cat = 'Regional'
            else:
                cat = 'Other'
            
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(g)
        
        for cat in sorted(categories.keys()):
            print(f"{cat}:")
            for g in sorted(categories[cat]):
                print(f"  - {g}")
            print()
        
        print(f"Total: {len(genres)} genres")
    except ImportError:
        print("Could not load genre_families.py")
        genres = sorted(set(AUDIODB_GENRE_MAP.values()))
        for g in genres:
            print(f"  - {g}")


def test_similar_artists(artists, lastfm_client):
    """Test Last.fm similar artist discovery features."""
    print("\n=== LAST.FM SIMILAR ARTISTS ===\n")
    
    if not lastfm_client.api_key:
        print("ERROR: LASTFM_API_KEY not set")
        return
    
    # Show similar artists for each seed
    for artist in artists:
        print(f"\n{'='*60}")
        print(f"Seed: {artist}")
        print(f"{'='*60}")
        
        similar = lastfm_client.get_similar_artists(artist, limit=10, min_match=0.3)
        
        if similar:
            print(f"\n  Similar artists (top {len(similar)}):")
            for a in similar:
                match_pct = a['match'] * 100
                print(f"    - {a['name']}: {match_pct:.1f}% match")
        else:
            print("\n  No similar artists found")
    
    # Show expanded pool across all seeds
    print(f"\n{'='*60}")
    print("EXPANDED ARTIST POOL (aggregated across all seeds)")
    print(f"{'='*60}")
    
    existing = set(a.lower() for a in artists)
    expanded = lastfm_client.expand_artist_pool(artists, existing, limit=20, min_match=0.4)
    
    if expanded:
        print(f"\n  Discovered {len(expanded)} new artists:\n")
        for a in expanded:
            match_pct = a['match'] * 100
            seed_info = f"from {a['seed']}"
            if a.get('count', 1) > 1:
                seed_info += f" (matched {a['count']} seeds)"
            print(f"    - {a['name']}: {match_pct:.1f}% match ({seed_info})")
    else:
        print("\n  No new artists discovered")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_artist_genre.py \"Artist Name\" [\"Artist 2\"] ...")
        print("       python test_artist_genre.py --list-genres")
        print("       python test_artist_genre.py --similar \"Artist 1\" [\"Artist 2\"] ...")
        sys.exit(1)
    
    if sys.argv[1] == "--list-genres":
        list_all_genres()
        return
    
    if sys.argv[1] == "--similar":
        if len(sys.argv) < 3:
            print("Usage: python test_artist_genre.py --similar \"Artist 1\" [\"Artist 2\"] ...")
            sys.exit(1)
        
        artists = sys.argv[2:]
        lastfm_client = LastFmClient()
        test_similar_artists(artists, lastfm_client)
        return
    
    # Load resources once
    try:
        df = pl.read_parquet(DATA_PATH)
    except Exception:
        print("Note: Could not load local parquet data (dataset check will be skipped).")
        df = pl.DataFrame({"artist_name": [], "genre": []})
    
    reassignment_map = load_reassignments()
    lastfm_client = LastFmClient()
    
    if not lastfm_client.api_key:
        print("Tip: Set LASTFM_API_KEY env var for Last.fm tag lookup")
    
    artists = sys.argv[1:]
    
    for artist in artists:
        print(f"\n{'='*70}")
        print(f"Artist: {artist}")
        print(f"{'='*70}")
        
        rows = check_dataset(artist, df)
        audiodb_genre = check_audiodb(artist)
        lastfm_genre = check_lastfm(artist, lastfm_client)
        reassignment = check_reassignment(artist, reassignment_map)
        show_final_genre(artist, reassignment, audiodb_genre, lastfm_genre, rows)


if __name__ == "__main__":
    main()
