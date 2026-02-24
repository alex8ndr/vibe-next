"""
I/O utilities for Vibe data pipeline.

Provides:
- Atomic write pattern (write to .tmp, validate, rename)
- Memory-efficient Parquet reading/writing with Polars
- Validation helpers
- Write locking to prevent concurrent corruption

The atomic write pattern ensures zero-downtime updates:
1. Acquire lock file
2. Write to temporary file
3. Validate the written data
4. Atomically rename to target (instant on same filesystem)
5. Release lock

This prevents the app from ever seeing partial/corrupted data.
"""
import os
import json
import platform
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from contextlib import contextmanager

import polars as pl

from paths import MANIFEST_FILE, get_temp_path


# =============================================================================
# Write Locking (prevents concurrent writer corruption)
# =============================================================================

@contextmanager
def write_lock(target_path: Path, timeout_seconds: int = 30):
    """
    Context manager for exclusive write access using a lock file.
    
    Prevents two concurrent pipeline runs from corrupting data.
    Uses O_CREAT|O_EXCL for atomic lock acquisition.
    """
    lock_path = target_path.with_suffix(target_path.suffix + ".lock")
    fd = None
    
    try:
        # Try to create lock file exclusively (fails if exists)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()}".encode())
        yield
    except FileExistsError:
        raise IOError(
            f"Write lock exists: {lock_path.name}\n"
            f"Another pipeline may be running. If not, delete the lock file."
        )
    finally:
        if fd is not None:
            os.close(fd)
        if lock_path.exists():
            lock_path.unlink()


# =============================================================================
# Atomic Write Pattern
# =============================================================================

def atomic_write_parquet(
    df: pl.DataFrame | pl.LazyFrame,
    target_path: Path,
    *,
    compression: str = "zstd",
    compression_level: int = 12,
    validate: Callable[[pl.DataFrame], bool] | None = None,
    verbose: bool = False,
) -> None:
    """
    Write a Polars DataFrame to Parquet atomically with write locking.
    
    Steps:
    1. Acquire exclusive write lock
    2. Write to {target}.tmp
    3. Validate the temp file (optional custom validator)
    4. Atomically rename temp → target
    5. Release lock
    
    Args:
        df: Polars DataFrame or LazyFrame to write
        target_path: Final destination path
        compression: Compression codec (zstd recommended)
        compression_level: Compression level (12 is good balance)
        validate: Optional validation function (receives DataFrame, returns bool)
        verbose: Print progress messages
    
    Raises:
        ValueError: If validation fails
        OSError: If atomic rename fails
        IOError: If another writer holds the lock
    """
    target_path = Path(target_path)
    temp_path = get_temp_path(target_path)
    
    # Ensure parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Collect LazyFrame if needed (without streaming - stable on all platforms)
    if isinstance(df, pl.LazyFrame):
        if verbose:
            print(f"  Collecting LazyFrame...")
        df = df.collect()
    
    # Use write lock to prevent concurrent corruption
    with write_lock(target_path):
        if verbose:
            print(f"  Writing to temp file: {temp_path.name}")
        
        # Write to temp file
        df.write_parquet(
            temp_path,
            compression=compression,
            compression_level=compression_level,
        )
        
        # Validate temp file
        try:
            if verbose:
                print(f"  Validating...")
            
            # Basic validation: can we read it back?
            df_check = pl.read_parquet(temp_path)
            
            # Row count check
            if len(df_check) == 0:
                raise ValueError("Written file is empty")
            
            if len(df_check) != len(df):
                raise ValueError(f"Row count mismatch: wrote {len(df)}, read {len(df_check)}")
            
            # Custom validation
            if validate is not None:
                if not validate(df_check):
                    raise ValueError("Custom validation failed")
            
            if verbose:
                print(f"  Validation passed ({len(df_check):,} rows)")
                
        except Exception as e:
            # Clean up temp file on validation failure
            if temp_path.exists():
                temp_path.unlink()
            raise ValueError(f"Validation failed: {e}") from e
        
        # Atomic rename (POSIX: rename() is atomic; Windows: replace() is atomic)
        if verbose:
            print(f"  Atomic rename: {temp_path.name} -> {target_path.name}")
        
        # os.replace is atomic on both POSIX and Windows
        os.replace(temp_path, target_path)
        
        if verbose:
            size_mb = target_path.stat().st_size / (1024 * 1024)
            print(f"  Wrote {target_path.name} ({size_mb:.1f} MB)")


def cleanup_temp_files(data_dir: Path, verbose: bool = False) -> int:
    """Remove any leftover .tmp files from failed writes."""
    count = 0
    for tmp_file in data_dir.glob("*.tmp"):
        if verbose:
            print(f"  Removing orphaned temp file: {tmp_file.name}")
        tmp_file.unlink()
        count += 1
    return count


# =============================================================================
# Reading Helpers
# =============================================================================

def read_parquet_safe(path: Path, columns: list[str] | None = None) -> pl.DataFrame:
    """
    Read a Parquet file safely, handling common issues.
    
    Args:
        path: Path to the Parquet file
        columns: Optional list of columns to read (memory optimization)
    
    Returns:
        Polars DataFrame
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    try:
        if columns:
            return pl.read_parquet(path, columns=columns)
        return pl.read_parquet(path)
    except Exception as e:
        # Check if it's a temp file issue
        temp_path = get_temp_path(path)
        if temp_path.exists():
            raise IOError(
                f"Failed to read {path.name}. "
                f"Found orphaned temp file - previous write may have failed. "
                f"Remove {temp_path.name} and retry."
            ) from e
        raise


def scan_parquet_lazy(path: Path) -> pl.LazyFrame:
    """
    Create a lazy scan of a Parquet file.
    
    This is memory-efficient as it doesn't load data until collect() is called.
    Supports predicate pushdown for filtering.
    
    Note: Do NOT use .collect(streaming=True) on Windows - it can cause crashes.
    Use .collect() instead.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    return pl.scan_parquet(path)


# =============================================================================
# CSV Reading (for legacy files)
# =============================================================================

def read_csv_zip(path: Path) -> pl.DataFrame:
    """Read a CSV file from a zip archive (legacy format)."""
    import zipfile
    from io import BytesIO
    
    with zipfile.ZipFile(path, 'r') as zf:
        # Find the CSV file in the archive
        csv_names = [n for n in zf.namelist() if n.endswith('.csv')]
        if not csv_names:
            raise ValueError(f"No CSV file found in {path}")
        
        csv_name = csv_names[0]
        with zf.open(csv_name) as f:
            content = f.read()
            return pl.read_csv(BytesIO(content), infer_schema_length=10000)


def read_input_file(
    path: Path,
    normalize_schema: bool = False,
) -> pl.DataFrame:
    """Read a data file, auto-detecting format (parquet, csv, csv.zip).
    
    Args:
        path: Path to the data file
        normalize_schema: If True, coerce types to canonical schema (from schema.py).
                         Use this when preparing data for merging.
    
    Returns:
        Polars DataFrame
    """
    path = Path(path)
    
    if path.suffix == '.parquet':
        df = pl.read_parquet(path)
    elif path.suffix == '.zip' or str(path).endswith('.csv.zip'):
        df = read_csv_zip(path)
    elif path.suffix == '.csv':
        df = pl.read_csv(path, infer_schema_length=10000)
    else:
        raise ValueError(f"Unknown file format: {path}")
    
    if normalize_schema:
        from schema import coerce_to_schema
        df = coerce_to_schema(df)
    
    return df


# =============================================================================
# Manifest Management
# =============================================================================

def load_manifest() -> dict[str, Any]:
    """Load the data manifest file."""
    if not MANIFEST_FILE.exists():
        return {}
    
    with open(MANIFEST_FILE, 'r') as f:
        return json.load(f)


def save_manifest(data: dict[str, Any]) -> None:
    """Save the data manifest file atomically."""
    temp_path = get_temp_path(MANIFEST_FILE)
    
    with open(temp_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    
    os.replace(temp_path, MANIFEST_FILE)


def update_manifest(
    *,
    operation: str,
    track_count: int | None = None,
    artist_count: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Update the manifest with new information."""
    manifest = load_manifest()
    
    manifest['last_updated'] = datetime.now().isoformat()
    manifest['last_operation'] = operation
    manifest['platform'] = platform.system()
    
    if track_count is not None:
        manifest['track_count'] = track_count
    if artist_count is not None:
        manifest['artist_count'] = artist_count
    if extra:
        manifest.update(extra)
    
    save_manifest(manifest)


# =============================================================================
# Validation Functions
# =============================================================================

def validate_encoded_dataset(df: pl.DataFrame) -> bool:
    """Validate an encoded dataset has required columns and reasonable data."""
    required_cols = ['artist_name', 'track_name', 'track_id']
    
    for col in required_cols:
        if col not in df.columns:
            print(f"  ✗ Missing required column: {col}")
            return False
    
    # Check for genre columns
    genre_cols = [c for c in df.columns if c.startswith('genre_')]
    if len(genre_cols) == 0:
        print(f"  ✗ No genre columns found")
        return False
    
    # Check for reasonable row count (prevent accidental truncation)
    if len(df) < 1000:
        print(f"  ⚠ Warning: Only {len(df)} rows (expected 100k+)")
        # Don't fail, just warn - might be intentional for testing
    
    return True


def validate_filtered_dataset(df: pl.DataFrame) -> bool:
    """Validate a filtered dataset."""
    required_cols = ['artist_name', 'track_name', 'track_id', 'genre']
    
    for col in required_cols:
        if col not in df.columns:
            print(f"  ✗ Missing required column: {col}")
            return False
    
    return True


# =============================================================================
# Scaler Parameter Management
# =============================================================================

def save_scaler_params(params: dict[str, tuple[float, float]]) -> None:
    """Save min/max scaler parameters to manifest."""
    manifest = load_manifest()
    manifest['scaler_params'] = {col: {'min': min_val, 'max': max_val} for col, (min_val, max_val) in params.items()}
    save_manifest(manifest)


def load_scaler_params() -> dict[str, tuple[float, float]] | None:
    """Load min/max scaler parameters from manifest."""
    manifest = load_manifest()
    if 'scaler_params' not in manifest:
        return None
    return {col: (v['min'], v['max']) for col, v in manifest['scaler_params'].items()}
