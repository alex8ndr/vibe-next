"""
Centralized path configuration for Vibe data pipeline.

All data paths are derived from VIBE_DATA_DIR environment variable.
Defaults to ./backend/data for local development.

Usage:
    from paths import DATA_DIR, RAW_DATASET, ENCODED_DATASET
"""
import os
from pathlib import Path

# Base data directory (configurable via environment)
# Default: backend/data relative to the scripts folder
_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR = Path(os.environ.get("VIBE_DATA_DIR", _DEFAULT_DATA_DIR)).resolve()

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Primary Data Files (Parquet format)
# =============================================================================

# Raw unprocessed dataset (converted from legacy CSV)
RAW_DATASET = DATA_DIR / "data.parquet"

# Filtered dataset (after removing excluded content)
FILTERED_DATASET = DATA_DIR / "data_filtered.parquet"

# Final encoded dataset for serving (what the app reads)
ENCODED_DATASET = DATA_DIR / "data_encoded.parquet"

# Incremental additions (new artists before merge)
ADDED_ARTISTS = DATA_DIR / "added_artists.parquet"

# =============================================================================
# Legacy CSV Files (for backward compatibility and conversion)
# =============================================================================

RAW_CSV_ZIP = DATA_DIR / "data.csv.zip"
FILTERED_CSV_ZIP = DATA_DIR / "data_filtered.csv.zip"
ADDED_ARTISTS_CSV_ZIP = DATA_DIR / "added_artists.csv.zip"

# =============================================================================
# External Datasets (for merging and genre enrichment)
# =============================================================================

EXTERNAL_DIR = DATA_DIR / "external"

# Preprocessed external tracks (output of preprocess_external_datasets.py)
YAMAC_TRACKS = EXTERNAL_DIR / "yamac_tracks.parquet"
ANANT_TRACKS = EXTERNAL_DIR / "anant_tracks.parquet"
ARCHIVE_3_TRACKS = EXTERNAL_DIR / "archive_3.parquet"
BRUCE_TRACKS = EXTERNAL_DIR / "bruce_spotify.parquet"
SERKAN_TRACKS = EXTERNAL_DIR / "serkan_tracks.parquet"

# Registry of external track datasets by name for CLI selection

def get_external_track_datasets() -> dict[str, Path]:
    """Scan EXTERNAL_DIR for all .parquet files and return {stem: path} dict."""
    if not EXTERNAL_DIR.is_dir():
        return {}
    return {p.stem: p for p in sorted(EXTERNAL_DIR.glob("*.parquet"))}

EXTERNAL_TRACK_DATASETS = get_external_track_datasets()

# Artist genre data — raw source CSVs (used by preprocess_genre_sources.py)
SERKAN_ARTISTS_CSV = EXTERNAL_DIR / "serkan-550k-spotify" / "artists (1).csv"
YAMAC_ARTISTS_CSV = EXTERNAL_DIR / "yamac-spotify-1920-2020" / "artists.csv"

# Preprocessed artist genre parquets (standardized schema, used at runtime)
GENRE_DIR = EXTERNAL_DIR / "genre"
SERKAN_GENRE = GENRE_DIR / "serkan.parquet"
YAMAC_GENRE = GENRE_DIR / "yamac.parquet"
VECTORQL_GENRE = GENRE_DIR / "vectorql.parquet"

# =============================================================================
# Metadata & Manifest
# =============================================================================

# Stores normalization stats, version info, last update time
MANIFEST_FILE = DATA_DIR / "manifest.json"

# Genre reassignment files directory
REASSIGNMENTS_DIR = DATA_DIR / "reassignments"

# =============================================================================
# Temporary Files (for atomic writes)
# =============================================================================

def get_temp_path(target: Path) -> Path:
    """Get temporary file path for atomic write pattern."""
    return target.with_suffix(target.suffix + ".tmp")


# =============================================================================
# Helpers
# =============================================================================

def ensure_parquet_exists(legacy_csv: Path, parquet_path: Path) -> Path:
    """Return parquet path, converting from CSV if needed."""
    if parquet_path.exists():
        return parquet_path
    
    if legacy_csv.exists():
        print(f"Note: {parquet_path.name} not found. Run convert_to_parquet.py first.")
        print(f"      Falling back to CSV: {legacy_csv.name}")
        return legacy_csv
    
    raise FileNotFoundError(f"Neither {parquet_path} nor {legacy_csv} found")


def get_input_dataset() -> Path:
    """Get the best available input dataset (prefers parquet)."""
    if RAW_DATASET.exists():
        return RAW_DATASET
    if RAW_CSV_ZIP.exists():
        return RAW_CSV_ZIP
    raise FileNotFoundError(f"No raw dataset found in {DATA_DIR}")


def get_filtered_dataset() -> Path:
    """Get the best available filtered dataset (prefers parquet)."""
    if FILTERED_DATASET.exists():
        return FILTERED_DATASET
    if FILTERED_CSV_ZIP.exists():
        return FILTERED_CSV_ZIP
    raise FileNotFoundError(f"No filtered dataset found in {DATA_DIR}")


def get_added_artists() -> Path | None:
    """Get added_artists file if it exists (prefers parquet)."""
    if ADDED_ARTISTS.exists():
        return ADDED_ARTISTS
    if ADDED_ARTISTS_CSV_ZIP.exists():
        return ADDED_ARTISTS_CSV_ZIP
    return None


# =============================================================================
# Debug / Info
# =============================================================================

def print_paths():
    """Print current path configuration (useful for debugging)."""
    print(f"VIBE_DATA_DIR: {DATA_DIR}")
    print(f"  RAW_DATASET:      {RAW_DATASET} {'✓' if RAW_DATASET.exists() else '✗'}")
    print(f"  FILTERED_DATASET: {FILTERED_DATASET} {'✓' if FILTERED_DATASET.exists() else '✗'}")
    print(f"  ENCODED_DATASET:  {ENCODED_DATASET} {'✓' if ENCODED_DATASET.exists() else '✗'}")
    print(f"  ADDED_ARTISTS:    {ADDED_ARTISTS} {'✓' if ADDED_ARTISTS.exists() else '✗'}")
    print(f"  (Legacy CSV)")
    print(f"  RAW_CSV_ZIP:      {RAW_CSV_ZIP} {'✓' if RAW_CSV_ZIP.exists() else '✗'}")
    print(f"  FILTERED_CSV_ZIP: {FILTERED_CSV_ZIP} {'✓' if FILTERED_CSV_ZIP.exists() else '✗'}")
    print(f"  (External track datasets)")
    for name, path in get_external_track_datasets().items():
        print(f"  {name:20s} {path} {'✓' if path.exists() else '✗'}")
    print(f"  (External artist CSVs)")
    print(f"  SERKAN_ARTISTS:   {SERKAN_ARTISTS_CSV} {'✓' if SERKAN_ARTISTS_CSV.exists() else '✗'}")
    print(f"  YAMAC_ARTISTS:    {YAMAC_ARTISTS_CSV} {'✓' if YAMAC_ARTISTS_CSV.exists() else '✗'}")
    print(f"  (Preprocessed genre sources)")
    print(f"  SERKAN_GENRE:     {SERKAN_GENRE} {'✓' if SERKAN_GENRE.exists() else '✗'}")
    print(f"  YAMAC_GENRE:      {YAMAC_GENRE} {'✓' if YAMAC_GENRE.exists() else '✗'}")
    print(f"  VECTORQL_GENRE:   {VECTORQL_GENRE} {'✓' if VECTORQL_GENRE.exists() else '✗'}")


if __name__ == "__main__":
    print_paths()
