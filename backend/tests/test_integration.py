#!/usr/bin/env python3
"""Quick integration test for the recommendation engine."""

import gc
import shutil
import sys
from tempfile import mkdtemp
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

tmp_dir = Path(mkdtemp(prefix='music-data-cache-test-'))
cached = None
try:
    cache_dir = tmp_dir / '.music_data_cache'
    data.save_cache_bundle(cache_dir, tracks_path, artists_path)

    cached = MusicData(source)
    restored = cached.load_cache_bundle(cache_dir, tracks_path, artists_path)
    assert restored, 'Cache bundle should restore cleanly'
    assert cached.track_count == data.track_count
    assert cached.get_track_id(0) == data.get_track_id(0)
    assert cached.get_track_name(0) == data.get_track_name(0)
    print('Cache roundtrip test: PASS')

    # Smoke test recommendations from cached/mmap load
    cached_recs, _ = generate_recommendations(cached, ['Taylor Swift'], max_artists=3)
    assert cached_recs, 'Cached recommendations should not be empty'
    print('Cached recommendation smoke test: PASS')
finally:
    cached = None
    gc.collect()
    shutil.rmtree(tmp_dir, ignore_errors=True)

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
