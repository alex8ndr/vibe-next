#!/usr/bin/env python3
"""
Preprocess external artist genre sources into standardized parquet files.

Reads raw CSV/parquet data from Serkan, Yamac, and Vectorql datasets and
writes standardized parquet files to data/external/genre/ with a unified schema:

  - id: Spotify artist ID (String)
  - name: artist name (String)
  - popularity: Spotify popularity score (Int64, nullable)
  - genres: raw sub-genre tags (List[String])
  - fallback: broad genre category (String, nullable — only Serkan has this)

Genre mapping to our 82-genre vocabulary happens at runtime (not here),
so changes to the vocabulary don't require re-running this script.

Usage:
    python preprocess_genre_sources.py
    python preprocess_genre_sources.py --source serkan yamac vectorql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from io_utils import atomic_write_parquet
from paths import (
    EXTERNAL_DIR,
    GENRE_DIR,
    SERKAN_ARTISTS_CSV,
    SERKAN_GENRE,
    VECTORQL_GENRE,
    YAMAC_ARTISTS_CSV,
    YAMAC_GENRE,
)


def _parse_genres_list(raw: str | None) -> list[str]:
    """Parse a Python list-repr string like \"['groove metal', 'metal']\" into a list."""
    if not raw or not isinstance(raw, str):
        return []
    stripped = raw.strip()
    if stripped in ("[]", ""):
        return []
    inner = stripped.lstrip("[").rstrip("]")
    tags = []
    for item in inner.split(","):
        cleaned = item.strip().strip("'").strip('"').strip()
        if cleaned:
            tags.append(cleaned)
    return tags


def _standardize_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Ensure output has the standard columns in the right types."""
    schema = {
        "id": pl.String,
        "name": pl.String,
        "popularity": pl.Int64,
        "genres": pl.List(pl.String),
        "fallback": pl.String,
    }
    exprs = []
    for col, dtype in schema.items():
        if col in df.columns:
            exprs.append(pl.col(col).cast(dtype))
        else:
            exprs.append(pl.lit(None).cast(dtype).alias(col))
    return df.select(exprs)


def preprocess_serkan() -> pl.DataFrame | None:
    """Preprocess Serkan 550k artists CSV."""
    if not SERKAN_ARTISTS_CSV.exists():
        print(f"  Not found: {SERKAN_ARTISTS_CSV}")
        return None

    print(f"  Reading {SERKAN_ARTISTS_CSV}...")
    df = pl.read_csv(SERKAN_ARTISTS_CSV, infer_schema_length=1000)
    print(f"  Raw rows: {len(df):,}")

    df = df.with_columns(
        pl.col("genres")
        .map_elements(_parse_genres_list, return_dtype=pl.List(pl.String))
        .alias("genres"),
        pl.col("main_genre").cast(pl.String).alias("fallback"),
    )

    df = df.filter(pl.col("id").is_not_null() & pl.col("name").is_not_null())
    return _standardize_schema(df)


def preprocess_yamac() -> pl.DataFrame | None:
    """Preprocess Yamac 1920-2020 artists CSV."""
    if not YAMAC_ARTISTS_CSV.exists():
        print(f"  Not found: {YAMAC_ARTISTS_CSV}")
        return None

    print(f"  Reading {YAMAC_ARTISTS_CSV}...")
    df = pl.read_csv(YAMAC_ARTISTS_CSV, infer_schema_length=1000)
    print(f"  Raw rows: {len(df):,}")

    df = df.with_columns(
        pl.col("genres")
        .map_elements(_parse_genres_list, return_dtype=pl.List(pl.String))
        .alias("genres"),
    )

    df = df.filter(pl.col("id").is_not_null() & pl.col("name").is_not_null())
    return _standardize_schema(df)


def preprocess_vectorql() -> pl.DataFrame | None:
    """Preprocess Vectorql parquet files (artists + artist_genres join)."""
    artists_path = EXTERNAL_DIR / "vectorql" / "artists.parquet"
    genres_path = EXTERNAL_DIR / "vectorql" / "artist_genres.parquet"

    if not artists_path.exists() or not genres_path.exists():
        print(f"  Not found: {EXTERNAL_DIR / 'vectorql'}")
        return None

    print(f"  Reading {artists_path}...")
    artists = pl.read_parquet(artists_path)
    print(f"  Artists: {len(artists):,}")

    print(f"  Reading {genres_path}...")
    genres = pl.read_parquet(genres_path)
    print(f"  Genre rows: {len(genres):,}")

    # Aggregate genres per artist into a list
    genres_agg = genres.group_by("artist_rowid").agg(pl.col("genre").alias("genres"))

    # Join artists with aggregated genres
    df = artists.join(genres_agg, left_on="rowid", right_on="artist_rowid", how="left")

    # Fill null genre lists with empty list
    df = df.with_columns(
        pl.when(pl.col("genres").is_null())
        .then(pl.lit([]).cast(pl.List(pl.String)))
        .otherwise(pl.col("genres"))
        .alias("genres")
    )

    df = df.filter(pl.col("id").is_not_null() & pl.col("name").is_not_null())
    return _standardize_schema(df)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess external genre sources into standardized parquet files."
    )
    parser.add_argument(
        "--source",
        nargs="*",
        choices=["serkan", "yamac", "vectorql"],
        help="Sources to process (default: all)",
    )
    args = parser.parse_args()

    GENRE_DIR.mkdir(parents=True, exist_ok=True)

    sources = args.source or ["serkan", "yamac", "vectorql"]

    processors = {
        "serkan": (preprocess_serkan, SERKAN_GENRE),
        "yamac": (preprocess_yamac, YAMAC_GENRE),
        "vectorql": (preprocess_vectorql, VECTORQL_GENRE),
    }

    for name in sources:
        print(f"\n--- {name} ---")
        processor, output_path = processors[name]
        df = processor()
        if df is None:
            continue

        # Keep only artists with at least genres or fallback
        df = df.filter(
            (pl.col("genres").list.len() > 0) | pl.col("fallback").is_not_null()
        )

        print(f"  Output rows: {len(df):,}")
        atomic_write_parquet(df, output_path, compression="zstd", compression_level=12)
        print(f"  Wrote {output_path}")


if __name__ == "__main__":
    main()
