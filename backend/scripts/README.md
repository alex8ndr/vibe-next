# Data Processing Scripts

These scripts are for **offline data processing** - they are NOT run by the production server.
Run them locally or on a dev machine, then deploy the updated `data_encoded.parquet`.

## Structure

```
scripts/
├── pipeline/         # Data transformation pipeline
│   ├── filter_data.py
│   └── process_data.py
├── discovery/        # Artist/album discovery
│   ├── add_artist.py       # Add new artists
│   ├── check_added.py      # Manage added_artists dataset
│   ├── grow_artist.py      # Add more tracks to existing artists
│   ├── expand_artists.py
│   ├── check_new_albums.py
│   ├── check_trending.py
│   └── backfill_albums.py
├── track_dedup.py    # Track/artist deduplication logic
├── utils.py          # Shared utilities (API clients, genre mapping)
├── genre_families.py # Genre definitions
├── paths.py          # Path configuration
└── README.md
```

## Technology Stack

All scripts use **Polars** for memory-efficient DataFrame operations:
- Parquet as primary format (replaced CSV)
- Unicode-aware artist/track normalization
- Weighted genre matching from Last.fm tags

## Pipeline Scripts

### `pipeline/filter_data.py`
Filters raw data before processing. This is the first pipeline step.

**Filters applied:**
1. Null filtering (artist_name, track_name, track_id required)
2. Deduplication by track_id
3. Invalid energy filter (energy > 0.01)
4. Artist genre reassignments
5. Genre family filtering

```bash
cd backend/scripts/pipeline
python filter_data.py -v
```

### `pipeline/process_data.py`
Processes filtered data into the optimized parquet file used by the backend.

```bash
cd backend/scripts/pipeline

# Basic usage (reads data_filtered.parquet from data dir)
python process_data.py -v

# With explicit paths
python process_data.py -i ../../data/data_filtered.parquet -o ../../data/data_encoded.parquet -v
```

## Discovery Scripts

### `discovery/add_artist.py`
Add new artists to the dataset via ReccoBeats API.

```bash
cd backend/scripts/discovery

# Interactive mode (recommended)
python add_artist.py

# By Spotify track URL
python add_artist.py --track "https://open.spotify.com/track/xxx"

# By album URL (efficient for existing artists)
python add_artist.py --album "https://open.spotify.com/album/xxx"

# By artist name (searches via Deezer)
python add_artist.py --names "Radiohead, Coldplay"

# Expand to similar artists via Last.fm
python add_artist.py --names "Radiohead" --expand 5
```

### `discovery/check_added.py`
Manage the added_artists.parquet dataset (list, delete, reclassify).

```bash
# List all added artists
python check_added.py --list
python check_added.py --list --tracks  # Also show track names

# List tracks for a specific artist
python check_added.py --list-tracks "Radiohead"

# Delete artists from added_artists (not main dataset)
python check_added.py --delete "Radiohead,Coldplay"
python check_added.py --delete all

# Change artist genre
python check_added.py --reclassify "Radiohead=alt-rock"
python check_added.py --reclassify "Radiohead=api"  # Re-fetch from TheAudioDB
```

### `discovery/grow_artist.py`
Add more tracks to existing artists using simple top-tracks logic.

```bash
# Add 20 more tracks (default)
python grow_artist.py "Radiohead"
python grow_artist.py "Radiohead" --count 30

# From track URL
python grow_artist.py --track "https://open.spotify.com/track/xxx"

# Ensure specific songs are included
python grow_artist.py "Radiohead" --songs "Creep, Paranoid Android"

# Actually save changes
python grow_artist.py "Radiohead" --update
```

### `discovery/check_new_albums.py`
Check an artist for albums not in the dataset. Can add missing albums.

```bash
# Check what albums are missing (dry-run)
python check_new_albums.py "Taylor Swift"
python check_new_albums.py --url "https://open.spotify.com/artist/xxx"

# Show all albums (including ones in dataset)
python check_new_albums.py "Taylor Swift" --all

# Actually add missing albums to dataset
python check_new_albums.py "Taylor Swift" --update

# Prioritize specific songs when adding
python check_new_albums.py "Taylor Swift" --update --songs "Shake It Off, Blank Space"
```

### `discovery/check_trending.py`
Check trending artists from Spotify charts against the dataset.

```bash
# Check global top 50 (dry-run)
python check_trending.py

# Check viral charts
python check_trending.py --viral

# Add missing trending artists
python check_trending.py --update --max-add 10
```

### `discovery/backfill_albums.py`
Batch check artists already in dataset for missing albums.

```bash
# Check artists with fewest tracks (likely incomplete)
python backfill_albums.py --limit 50

# Add missing albums
python backfill_albums.py --update
```

### `discovery/expand_artists.py`
Expand dataset with similar artists via Last.fm.

```bash
# Discover similar artists (dry-run)
python expand_artists.py --limit 20

# From specific seeds
python expand_artists.py --seeds "Radiohead,Bjork" --limit 10

# Add discovered artists
python expand_artists.py --update --limit 20
```

Requires `LASTFM_API_KEY` environment variable.

## Shared Modules

### `track_dedup.py`
Track and artist deduplication with Unicode normalization:
- Case-insensitive matching ("RADIOHEAD" == "Radiohead")
- Accent normalization ("Björk" == "Bjork")
- "The" prefix handling ("The Beatles" == "Beatles")
- Track variant stripping ("Song (Remastered)" → "Song")

### `utils.py`
Shared utilities including:
- `ReccoBeatsClient` - API client for track/artist data
- `LastFmClient` - API client for tags and similar artists
- Genre mapping with weighted scoring
- Parquet I/O utilities

### `genre_families.py`
Genre family definitions. Edit this to modify genre mappings.

### `paths.py`
Path configuration using `VIBE_DATA_DIR` environment variable.

## Full Workflow

1. **Raw data files** are in `backend/data/`:
   - `data.parquet` - Main dataset
   - `added_artists.parquet` - Additional artists (from discovery scripts)

2. **Add new artists** (optional):
   ```bash
   cd backend/scripts/discovery
   python add_artist.py
   ```

3. **Run pipeline**:
   ```bash
   cd backend/scripts/pipeline
   python filter_data.py -v       # Creates data_filtered.parquet
   python process_data.py -v      # Creates data_encoded.parquet
   ```

4. **Commit and redeploy** to pick up the new data.

## Dependencies

Install all dependencies:
```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Key packages:
- `polars` - DataFrame operations
- `requests` - API calls
- `python-dotenv` - Environment configuration

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VIBE_DATA_DIR` | Data directory path | `backend/data` |
| `LASTFM_API_KEY` | Last.fm API key | None (optional) |

Get a free Last.fm API key at: https://www.last.fm/api/account/create
