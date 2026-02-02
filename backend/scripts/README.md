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
│   ├── add_artist.py
│   ├── expand_artists.py
│   ├── check_new_albums.py
│   ├── check_trending.py
│   └── backfill_albums.py
├── utils.py          # Shared utilities
├── genre_families.py # Genre definitions
└── README.md
```

## Pipeline Scripts

### `pipeline/process_data.py`
Processes raw Spotify data into the optimized parquet file used by the backend.

```bash
cd backend/scripts/pipeline

# Basic usage (expects data.csv.zip in ../../data/)
python process_data.py -v

# Specify paths explicitly
python process_data.py -i /path/to/data.csv.zip -o ../../data/data_encoded.parquet -v

# With merged artists
python process_data.py -i ../../data/data.csv.zip -o ../../data/data_encoded.parquet --merge ../../data/added_artists.csv.zip -v
```

### `pipeline/filter_data.py`
Filters raw data before processing (optional preprocessing step).

## Discovery Scripts

### `discovery/add_artist.py`
Add new artists to the dataset via ReccoBeats API.

```bash
cd backend/scripts/discovery

# Interactive mode (recommended)
python add_artist.py

# By Spotify track URL
python add_artist.py --track "https://open.spotify.com/track/xxx"

# By artist name
python add_artist.py --names "Radiohead, Coldplay"
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
```

### `discovery/check_trending.py`
Check trending artists from Spotify charts against the dataset.

```bash
# Check global top 50 (dry-run)
python check_trending.py

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

## Shared Files

### `genre_families.py`
Genre definitions used by `process_data.py`. Edit this to modify genre mappings.

### `utils.py`
Shared utilities for API clients, data loading, and deduplication.

## Full Workflow

1. **Raw data files** are in `backend/data/`:
   - `data.csv.zip` - Main dataset
   - `added_artists.csv.zip` - Additional artists (optional)

2. **Add new artists** (optional):
   ```bash
   cd backend/scripts/discovery
   python add_artist.py
   ```

3. **Process data**:
   ```bash
   cd backend/scripts/pipeline
   python process_data.py -v -o ../../data/data_encoded.parquet --merge ../../data/added_artists.csv.zip
   ```

4. **Commit and redeploy** to pick up the new data.

## Dependencies

These scripts need additional packages not required by the production server:
```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Note: The production server uses Polars for memory efficiency, but these scripts still use pandas/scikit-learn for preprocessing.
