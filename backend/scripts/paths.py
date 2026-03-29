"""
Centralized path configuration for Vibe data pipeline.

All data paths are derived from VIBE_DATA_DIR environment variable.
Defaults to ./backend/data for local development.

Usage:
    from paths import DATA_DIR, RAW_DATASET, TRACKS_DATASET, ARTISTS_DATASET
"""
import os
from dataclasses import dataclass
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

# Final serving datasets (what the app reads)
TRACKS_DATASET = DATA_DIR / "tracks.parquet"
ARTISTS_DATASET = DATA_DIR / "artists.parquet"

# Legacy single-file output (deprecated)
ENCODED_DATASET = DATA_DIR / "data_encoded.parquet"

# Incremental additions (new artists before merge)
ADDED_ARTISTS = DATA_DIR / "added_artists.parquet"

# =============================================================================
# External Datasets (for merging and genre enrichment)
# =============================================================================

EXTERNAL_DIR = DATA_DIR / "external"

# Registry of external track datasets by name for CLI selection

def get_external_track_datasets() -> dict[str, Path]:
    """Scan EXTERNAL_DIR for all .parquet files and return {stem: path} dict."""
    if not EXTERNAL_DIR.is_dir():
        return {}
    return {p.stem: p for p in sorted(EXTERNAL_DIR.glob("*.parquet"))}

EXTERNAL_TRACK_DATASETS = get_external_track_datasets()


def get_all_track_datasets() -> dict[str, Path]:
    """Get all available track datasets as a unified {name: path} registry.

    Includes core datasets (data, added_artists) and all external parquets.
    Only includes datasets whose files exist on disk.
    """
    datasets = {}
    if RAW_DATASET.exists():
        datasets["data"] = RAW_DATASET
    if ADDED_ARTISTS.exists():
        datasets["added_artists"] = ADDED_ARTISTS
    for name, path in get_external_track_datasets().items():
        if name not in datasets:
            datasets[name] = path
    return datasets


def get_selectable_track_datasets() -> dict[str, Path]:
    """Get datasets available for CLI selection (excludes added_artists overlay)."""
    datasets = {}
    if RAW_DATASET.exists():
        datasets["data"] = RAW_DATASET
    for name, path in get_external_track_datasets().items():
        if name not in datasets:
            datasets[name] = path
    return datasets

# Artist genre data — raw source CSVs (used by preprocess_genre_sources.py)
SERKAN_ARTISTS_CSV = EXTERNAL_DIR / "serkan-550k-spotify" / "artists (1).csv"
YAMAC_ARTISTS_CSV = EXTERNAL_DIR / "yamac-spotify-1920-2020" / "artists.csv"

# Preprocessed artist genre parquets (standardized schema, used at runtime)
GENRE_DIR = EXTERNAL_DIR / "genre"
SERKAN_GENRE = GENRE_DIR / "serkan.parquet"
YAMAC_GENRE = GENRE_DIR / "yamac.parquet"
VECTORQL_GENRE = GENRE_DIR / "vectorql.parquet"
MALTE_GENRE = GENRE_DIR / "malte.parquet"

# Malte SQLite source (used by preprocess_genre_sources.py)
MALTE_DIR = EXTERNAL_DIR / "malte"
MALTE_SQLITE = MALTE_DIR / "spotify.sqlite"
MALTE_SQLITE_ZIP = MALTE_DIR / "spotify.sqlite.zip"


@dataclass(frozen=True)
class GenreSource:
    """Runtime artist-genre source definition."""

    name: str
    path: Path


# Source precedence for lookup conflict resolution.
# Earlier sources win when multiple datasets contain the same normalized artist.
GENRE_SOURCES: tuple[GenreSource, ...] = (
    GenreSource("yamac", YAMAC_GENRE),
    GenreSource("vectorql", VECTORQL_GENRE),
    GenreSource("serkan", SERKAN_GENRE),
    GenreSource("malte", MALTE_GENRE),
)


def get_genre_sources() -> tuple[GenreSource, ...]:
    """Return artist-genre sources in runtime precedence order."""
    return GENRE_SOURCES

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

def get_input_dataset() -> Path:
    """Get the raw input dataset."""
    if RAW_DATASET.exists():
        return RAW_DATASET
    raise FileNotFoundError(f"No raw dataset found in {DATA_DIR}")


def get_filtered_dataset() -> Path:
    """Get the filtered dataset."""
    if FILTERED_DATASET.exists():
        return FILTERED_DATASET
    raise FileNotFoundError(f"No filtered dataset found in {DATA_DIR}")


def get_serving_datasets() -> tuple[Path, Path]:
    """Get the split serving datasets (tracks, artists)."""
    missing = []
    if not TRACKS_DATASET.exists():
        missing.append(TRACKS_DATASET)
    if not ARTISTS_DATASET.exists():
        missing.append(ARTISTS_DATASET)
    if missing:
        missing_str = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(f"Missing serving dataset(s): {missing_str}")
    return TRACKS_DATASET, ARTISTS_DATASET


def get_added_artists() -> Path | None:
    """Get added_artists file if it exists."""
    if ADDED_ARTISTS.exists():
        return ADDED_ARTISTS
    return None


# =============================================================================
# Debug / Info
# =============================================================================

def print_paths():
    """Print current path configuration (useful for debugging)."""
    print(f"VIBE_DATA_DIR: {DATA_DIR}")
    print(f"  RAW_DATASET:      {RAW_DATASET} {'✓' if RAW_DATASET.exists() else '✗'}")
    print(f"  FILTERED_DATASET: {FILTERED_DATASET} {'✓' if FILTERED_DATASET.exists() else '✗'}")
    print(f"  TRACKS_DATASET:   {TRACKS_DATASET} {'✓' if TRACKS_DATASET.exists() else '✗'}")
    print(f"  ARTISTS_DATASET:  {ARTISTS_DATASET} {'✓' if ARTISTS_DATASET.exists() else '✗'}")
    print(f"  ENCODED_DATASET:  {ENCODED_DATASET} {'✓' if ENCODED_DATASET.exists() else '✗'}  (deprecated)")
    print(f"  ADDED_ARTISTS:    {ADDED_ARTISTS} {'✓' if ADDED_ARTISTS.exists() else '✗'}")
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
    print(f"  MALTE_GENRE:      {MALTE_GENRE} {'✓' if MALTE_GENRE.exists() else '✗'}")


if __name__ == "__main__":
    print_paths()
