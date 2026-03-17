#!/usr/bin/env python3
"""Quick integration test for the recommendation engine."""

import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
from logic import MusicData, ParquetDataSource, generate_recommendations

tracks_path = Path(__file__).parent.parent / 'data' / 'tracks.parquet'
artists_path = Path(__file__).parent.parent / 'data' / 'artists.parquet'
source = ParquetDataSource(tracks_path, artists_path)
data = MusicData(source)
data.load()
print(f'Loaded {data.track_count:,} tracks')

# Test single artist
recs, meta = generate_recommendations(data, ['Taylor Swift'], max_artists=3)
print(f'Single artist test: {len(recs)} artists recommended')
for artist in recs:
    print(f'  - {artist}: {len(recs[artist])} tracks')

# Test multiple diverse artists
recs, meta = generate_recommendations(data, ['Metallica', 'Taylor Swift'], max_artists=3, debug=True, debug_audio=True)
print(f'Multi-artist test: {len(recs)} artists recommended')
print(f'  Num seeds: {meta.get("num_seeds", "N/A")}')
for artist in recs:
    print(f'  - {artist}: {len(recs[artist])} tracks')

print('All tests passed!')
