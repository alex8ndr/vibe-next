"""Test recommendations with real data."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
from logic import MusicData, ParquetDataSource, generate_recommendations

data = MusicData(ParquetDataSource(Path(__file__).parent.parent / "data" / "data_encoded.parquet"))
data.load()
print(f"Loaded {len(data.df)} tracks, {len(data.artists_list)} artists\n")

def test_query(artists, track_ids=None, label=""):
    print(f"{'='*60}")
    print(f"QUERY: {label or ', '.join(artists)}")
    print(f"{'='*60}")
    recs, meta = generate_recommendations(
        data, 
        input_artists=artists,
        track_ids=track_ids,
        max_artists=8,
        debug=True,
        debug_audio=True
    )
    
    if meta.get("input_genre_profile"):
        print("Input genres:", meta["input_genre_profile"])
    if meta.get("num_seeds"):
        print(f"Seeds used: {meta['num_seeds']}")
    print()
    
    for artist, tracks in recs.items():
        genre_info = ""
        if meta.get("debug", {}).get(artist, {}).get("genre_profile"):
            genres = meta["debug"][artist]["genre_profile"]
            genre_info = f" [{', '.join(g['genre'] for g in genres[:2])}]"
        print(f"  {artist}{genre_info}")
        for t in tracks[:2]:
            print(f"    - {t['track_name']}")
    print()

# Test 1: Single artist (should show variety within artist)
test_query(["Taylor Swift"])

# Test 2: Two similar artists (should show intersection - dance pop)
test_query(["Taylor Swift", "Dua Lipa"])

# Test 3: Two contrasting artists (should show mix, not forced middle)
test_query(["Taylor Swift", "Metallica"])

# Test 4: Very different artists (Gemini's Slayer+Enya scenario)
if "Slayer" in data.artists_list and "Enya" in data.artists_list:
    test_query(["Slayer", "Enya"])
else:
    # Find similar contrasting pair
    test_query(["Metallica", "Enya"] if "Enya" in data.artists_list else ["Metallica", "Adele"])
