"""
Centralized path configuration for Vibe data pipeline.

All data paths are derived from VIBE_DATA_DIR environment variable.
Defaults to ./backend/data for local development.

Usage:
    from paths import DATA_DIR, TRACKS_DATASET, ARTISTS_DATASET
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

# Filtered dataset (after removing excluded content)
FILTERED_DATASET = DATA_DIR / "data_filtered.parquet"

# Final serving datasets (what the app reads)
TRACKS_DATASET = DATA_DIR / "tracks.parquet"
ARTISTS_DATASET = DATA_DIR / "artists.parquet"

# Encoded dataset (used by incremental_update)
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

    Includes added_artists and all external parquets.
    Only includes datasets whose files exist on disk.
    """
    datasets = {}
    if ADDED_ARTISTS.exists():
        datasets["added_artists"] = ADDED_ARTISTS
    for name, path in get_external_track_datasets().items():
        if name not in datasets:
            datasets[name] = path
    return datasets


def get_selectable_track_datasets() -> dict[str, Path]:
    """Get datasets available for CLI selection (excludes added_artists overlay)."""
    return dict(get_external_track_datasets())

# Preprocessed artist genre parquets directory
GENRE_DIR = EXTERNAL_DIR / "genre"


@dataclass(frozen=True)
class GenreSource:
    """Runtime artist-genre source definition."""

    name: str
    path: Path


# Genre source precedence for lookup conflict resolution.
# Sources found in GENRE_DIR are sorted by this priority (lower = higher priority).
# Sources not listed here get priority 999 and sort alphabetically.
_GENRE_SOURCE_PRIORITY: dict[str, int] = {
    "custom": 0,
    "yamac": 1,
    "malte": 2,
    "vectorql": 3,
    "serkan": 4,
    "musicbrainz": 5,
    "discogs": 6,
}


def get_genre_sources() -> tuple[GenreSource, ...]:
    """Discover and return artist-genre sources in precedence order.
    
    Scans GENRE_DIR for .parquet files and sorts by configured priority.
    """
    if not GENRE_DIR.is_dir():
        return ()
    files = sorted(
        GENRE_DIR.glob("*.parquet"),
        key=lambda p: (_GENRE_SOURCE_PRIORITY.get(p.stem, 999), p.stem),
    )
    return tuple(GenreSource(p.stem, p) for p in files)

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
    """Get the largest available track dataset as primary input."""
    ext = get_external_track_datasets()
    if ext:
        return max(ext.values(), key=lambda p: p.stat().st_size if p.exists() else 0)
    raise FileNotFoundError(f"No track datasets found in {DATA_DIR}")


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
    print(f"  FILTERED_DATASET: {FILTERED_DATASET} {'✓' if FILTERED_DATASET.exists() else '✗'}")
    print(f"  TRACKS_DATASET:   {TRACKS_DATASET} {'✓' if TRACKS_DATASET.exists() else '✗'}")
    print(f"  ARTISTS_DATASET:  {ARTISTS_DATASET} {'✓' if ARTISTS_DATASET.exists() else '✗'}")
    print(f"  ADDED_ARTISTS:    {ADDED_ARTISTS} {'✓' if ADDED_ARTISTS.exists() else '✗'}")
    print(f"  (External track datasets)")
    for name, path in get_external_track_datasets().items():
        print(f"  {name:20s} {path} {'✓' if path.exists() else '✗'}")
    print(f"  (Genre sources - precedence order)")
    for gs in get_genre_sources():
        print(f"    {gs.name:20s} {gs.path} {'✓' if gs.path.exists() else '✗'}")


if __name__ == "__main__":
    print_paths()
