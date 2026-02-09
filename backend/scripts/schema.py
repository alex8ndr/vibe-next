"""
Canonical schema definitions for Vibe data pipeline.

This module defines the expected schema for all parquet files in the pipeline.
All discovery scripts and pipeline stages should use these definitions to ensure
consistent data types across the entire workflow.

Schema flow:
    1. Discovery scripts (add_artist.py) → added_artists.parquet (RAW_SCHEMA)
    2. convert_to_parquet.py → data.parquet (RAW_SCHEMA)
    3. filter_data.py → data_filtered.parquet (RAW_SCHEMA)
    4. process_data.py → data_encoded.parquet (ENCODED_SCHEMA)

Type Philosophy:
    - Strings: pl.String (UTF-8)
    - IDs: pl.String (Spotify IDs are alphanumeric strings)
    - Integers: pl.Int64 (year, key, mode, time_signature)
    - Floats: pl.Float64 (audio features, popularity is converted for consistency)
    - Booleans: pl.Boolean (mode could be, but kept as Int for compatibility)
"""
from typing import Dict, List, Optional

import polars as pl

# =============================================================================
# Raw Data Schema (before encoding)
# =============================================================================

# Column definitions: (name, dtype, nullable, description)
# Using Float32 for audio features - sufficient precision for 0-1 ranges and saves ~50% memory
RAW_COLUMNS: List[tuple] = [
    # Identifiers
    ("track_id", pl.String, False, "Spotify track ID"),
    ("track_name", pl.String, False, "Track title"),
    ("artist_name", pl.String, False, "Artist name"),
    
    # Metadata
    ("genre", pl.String, False, "Genre label (from discovery or reassignment)"),
    ("year", pl.Int64, True, "Release year"),
    ("popularity", pl.Float32, True, "Spotify popularity (0-100)"),
    ("duration_ms", pl.Float32, True, "Track duration in milliseconds"),
    
    # Audio features (all normalized 0-1 except loudness/tempo)
    ("danceability", pl.Float32, True, "How suitable for dancing (0-1)"),
    ("energy", pl.Float32, True, "Perceptual intensity (0-1)"),
    ("key", pl.Int64, True, "Pitch class (0-11, -1 if unknown)"),
    ("loudness", pl.Float32, True, "Overall loudness in dB"),
    ("mode", pl.Int64, True, "Modality: 1=major, 0=minor"),
    ("speechiness", pl.Float32, True, "Presence of spoken words (0-1)"),
    ("acousticness", pl.Float32, True, "Acoustic confidence (0-1)"),
    ("instrumentalness", pl.Float32, True, "Instrumental confidence (0-1)"),
    ("liveness", pl.Float32, True, "Audience presence confidence (0-1)"),
    ("valence", pl.Float32, True, "Musical positivity (0-1)"),
    ("tempo", pl.Float32, True, "Estimated tempo in BPM"),
    ("time_signature", pl.Int64, True, "Estimated time signature (3-7)"),
]

# Quick lookup for column types
RAW_SCHEMA: Dict[str, pl.DataType] = {
    name: dtype for name, dtype, _, _ in RAW_COLUMNS
}

# Required columns (must be present)
RAW_REQUIRED_COLUMNS: List[str] = [
    name for name, _, nullable, _ in RAW_COLUMNS if not nullable
]

# Optional columns (can be missing)
RAW_OPTIONAL_COLUMNS: List[str] = [
    name for name, _, nullable, _ in RAW_COLUMNS if nullable
]

# Column order for consistency
RAW_COLUMN_ORDER: List[str] = [name for name, _, _, _ in RAW_COLUMNS]


# =============================================================================
# Encoded Data Schema (after process_data.py)
# =============================================================================

# process_data.py adds genre embedding columns (genre_*) and scaled features
# The exact genre columns depend on GENRE_DEFINITIONS in genre_families.py
# Base columns remain the same, plus normalized versions

ENCODED_ADDITIONAL_COLUMNS: List[str] = [
    # These are added by process_data.py - prefixed with 'genre_'
    # Actual columns depend on GENRE_DEFINITIONS
]


# =============================================================================
# Schema Validation
# =============================================================================

def validate_raw_schema(df: pl.DataFrame, strict: bool = False) -> tuple[bool, List[str]]:
    """
    Validate a DataFrame against the raw schema.
    
    Args:
        df: DataFrame to validate
        strict: If True, require all columns. If False, only check present columns.
    
    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []
    
    # Check required columns
    for col in RAW_REQUIRED_COLUMNS:
        if col not in df.columns:
            errors.append(f"Missing required column: {col}")
    
    if strict:
        for col in RAW_OPTIONAL_COLUMNS:
            if col not in df.columns:
                errors.append(f"Missing optional column: {col}")
    
    # Check types for present columns
    for col in df.columns:
        if col in RAW_SCHEMA:
            expected = RAW_SCHEMA[col]
            actual = df[col].dtype
            
            # Allow some type flexibility
            if not _types_compatible(actual, expected):
                errors.append(
                    f"Type mismatch for '{col}': expected {expected}, got {actual}"
                )
    
    return len(errors) == 0, errors


def _types_compatible(actual: pl.DataType, expected: pl.DataType) -> bool:
    """Check if two types are compatible (allowing numeric coercion)."""
    # Exact match
    if actual == expected:
        return True
    
    # String types
    if expected == pl.String:
        return actual in (pl.String, pl.Utf8, pl.Categorical)
    
    # Float types - accept any float or int (will be cast)
    if expected in (pl.Float64, pl.Float32):
        return actual.is_numeric()
    
    # Int types - accept any integer (will be cast)
    if expected in (pl.Int64, pl.Int32, pl.Int16, pl.Int8):
        return actual.is_integer() or actual.is_float()  # Allow float->int for year etc
    
    return False


def coerce_to_schema(df: pl.DataFrame, schema: Dict[str, pl.DataType] = None) -> pl.DataFrame:
    """
    Coerce a DataFrame's columns to match the expected schema.
    
    This is the preferred way to normalize schemas - call it once at data ingestion
    rather than at merge time.
    
    Args:
        df: DataFrame to coerce
        schema: Schema to use (defaults to RAW_SCHEMA)
    
    Returns:
        DataFrame with corrected types
    """
    if schema is None:
        schema = RAW_SCHEMA
    
    casts = []
    for col in df.columns:
        if col in schema:
            expected = schema[col]
            actual = df[col].dtype
            
            if actual != expected:
                # Cast to expected type
                casts.append(pl.col(col).cast(expected).alias(col))
    
    if casts:
        df = df.with_columns(casts)
    
    return df


def select_raw_columns(df: pl.DataFrame, include_extra: bool = False) -> pl.DataFrame:
    """
    Select only the canonical raw columns in the correct order.
    
    Args:
        df: DataFrame to select from
        include_extra: If True, include columns not in schema at the end
    
    Returns:
        DataFrame with columns in canonical order
    """
    # Select canonical columns that exist
    canonical = [c for c in RAW_COLUMN_ORDER if c in df.columns]
    
    if include_extra:
        # Add any extra columns at the end
        extra = [c for c in df.columns if c not in RAW_COLUMN_ORDER]
        canonical.extend(extra)
    
    return df.select(canonical)


# =============================================================================
# Schema Migration Helpers
# =============================================================================

def normalize_for_merge(df: pl.DataFrame) -> pl.DataFrame:
    """
    Normalize a DataFrame for safe merging with other datasets.
    
    This replaces the ad-hoc schema alignment in process_data.py.
    Call this on both DataFrames before pl.concat().
    
    Steps:
    1. Coerce types to canonical schema
    2. Remove index columns
    3. Select only known columns
    """
    # Remove pandas index artifacts
    if "Unnamed: 0" in df.columns:
        df = df.drop("Unnamed: 0")
    
    # Coerce to schema
    df = coerce_to_schema(df)
    
    return df


def get_schema_report(df: pl.DataFrame) -> str:
    """Generate a human-readable schema report for debugging."""
    lines = ["Schema Report:", "=" * 50]
    
    is_valid, errors = validate_raw_schema(df)
    lines.append(f"Valid: {'✓' if is_valid else '✗'}")
    
    if errors:
        lines.append("\nErrors:")
        for err in errors:
            lines.append(f"  - {err}")
    
    lines.append(f"\nColumns ({len(df.columns)}):")
    for col in df.columns:
        dtype = df[col].dtype
        expected = RAW_SCHEMA.get(col, "?")
        marker = "✓" if col in RAW_SCHEMA and _types_compatible(dtype, expected) else "?"
        lines.append(f"  {marker} {col}: {dtype} (expected: {expected})")
    
    return "\n".join(lines)


# =============================================================================
# Usage Examples
# =============================================================================

if __name__ == "__main__":
    # Example usage
    print("Raw Schema Columns:")
    for name, dtype, nullable, desc in RAW_COLUMNS:
        req = "optional" if nullable else "required"
        print(f"  {name}: {dtype} ({req}) - {desc}")
