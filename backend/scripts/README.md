# Data Processing Scripts

These scripts are for **offline data processing** - they are NOT run by the production server.
Run them locally or on a dev machine, then deploy the updated `data_encoded.parquet`.

## Scripts

### `process_data.py`
Processes raw Spotify data into the optimized parquet file used by the backend.

```bash
cd backend/scripts

# Basic usage (expects data.csv.zip in current directory)
python process_data.py -v

# Specify paths explicitly
python process_data.py -i /path/to/data.csv.zip -o ../data/data_encoded.parquet -v

# With merged artists
python process_data.py -i data.csv.zip -o ../data/data_encoded.parquet --merge added_artists.csv.zip -v
```

### `add_artist.py`
Add new artists to the dataset via ReccoBeats API.

```bash
cd backend/scripts

# Interactive mode (recommended)
python add_artist.py

# By Spotify track URL
python add_artist.py --track "https://open.spotify.com/track/xxx"

# By artist name
python add_artist.py --names "Radiohead, Coldplay"
```

### `genre_families.py`
Genre definitions used by `process_data.py`. Edit this to modify genre mappings.

## Full Workflow

1. **Place raw data files** in `backend/scripts/`:
   - `data.csv.zip` - Main dataset
   - `added_artists.csv.zip` - Additional artists (optional)

2. **Add new artists** (optional):
   ```bash
   python add_artist.py
   ```

3. **Process data**:
   ```bash
   python process_data.py -v -o ../data/data_encoded.parquet --merge added_artists.csv.zip
   ```

4. **Commit and redeploy** to pick up the new data.

## Dependencies

These scripts need additional packages not required by the production server:
```bash
pip install scikit-learn requests
```
