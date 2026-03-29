#!/usr/bin/env python3
"""
Preprocess external artist genre sources into standardized parquet files.

Reads raw CSV/parquet/SQLite data from Serkan, Yamac, Vectorql, and Malte
datasets and writes standardized parquet files to data/external/genre/ with a
unified schema:

  - id: Spotify artist ID (String)
  - name: artist name (String)
  - popularity: Spotify popularity score (Int64, nullable)
  - genres: raw sub-genre tags (List[String])
  - fallback: broad genre category (String, nullable — only Serkan has this)

Genre mapping to our 82-genre vocabulary happens at runtime (not here),
so changes to the vocabulary don't require re-running this script.

Usage:
    python preprocess_genre_sources.py
    python preprocess_genre_sources.py --source serkan yamac vectorql malte
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from io_utils import atomic_write_parquet
from paths import (
    EXTERNAL_DIR,
    GENRE_DIR,
    MALTE_GENRE,
    MALTE_SQLITE,
    MALTE_SQLITE_ZIP,
    SERKAN_ARTISTS_CSV,
    SERKAN_GENRE,
    get_genre_sources,
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


def _ensure_malte_sqlite() -> Path | None:
    """Return path to Malte SQLite DB, extracting zip if needed."""
    if MALTE_SQLITE.exists():
        return MALTE_SQLITE

    if not MALTE_SQLITE_ZIP.exists():
        print(f"  Not found: {MALTE_SQLITE} or {MALTE_SQLITE_ZIP}")
        return None

    MALTE_SQLITE.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Extracting {MALTE_SQLITE_ZIP}...")
    with zipfile.ZipFile(MALTE_SQLITE_ZIP, "r") as zf:
        if "spotify.sqlite" not in zf.namelist():
            print("  Zip file does not contain spotify.sqlite")
            return None
        zf.extract("spotify.sqlite", path=MALTE_SQLITE.parent)
    return MALTE_SQLITE


def preprocess_malte() -> pl.DataFrame | None:
    """Preprocess Malte SQLite into standardized artist-genre rows."""
    db_path = _ensure_malte_sqlite()
    if db_path is None:
        return None

    print(f"  Reading {db_path}...")
    conn = sqlite3.connect(db_path)
    # Some rows contain invalid UTF-8 byte sequences in artist names.
    # Use bytes + replacement decoding to keep preprocessing deterministic.
    conn.text_factory = bytes
    cur = conn.cursor()
    try:
        artist_meta: dict[str, tuple[str, int | None]] = {}
        artist_rows = 0
        for artist_id_raw, name_raw, popularity_raw in cur.execute(
            "SELECT id, name, popularity FROM artists"
        ):
            artist_rows += 1

            artist_id = _decode_sqlite_text(artist_id_raw)
            artist_name = _decode_sqlite_text(name_raw)
            if not artist_id or not artist_name:
                continue

            popularity: int | None
            try:
                popularity = int(popularity_raw) if popularity_raw is not None else None
            except (TypeError, ValueError):
                popularity = None

            artist_meta[artist_id] = (artist_name, popularity)

        tags_by_artist: dict[str, list[str]] = defaultdict(list)
        genre_rows = 0
        for artist_id_raw, genre_raw in cur.execute(
            """
                SELECT rag.artist_id, g.id
                FROM r_artist_genre rag
                JOIN genres g ON rag.genre_id = g.id
            """
        ):
            genre_rows += 1
            artist_id = _decode_sqlite_text(artist_id_raw)
            genre = _decode_sqlite_text(genre_raw)
            if artist_id and genre:
                tags_by_artist[artist_id].append(genre)
    finally:
        conn.close()

    print(f"  Artists: {artist_rows:,}")
    print(f"  Artist-genre rows: {genre_rows:,}")

    if not tags_by_artist or not artist_meta:
        return None

    out_rows: list[dict[str, object]] = []
    for artist_id, genres in tags_by_artist.items():
        meta = artist_meta.get(artist_id)
        if meta is None:
            continue
        name, popularity = meta
        out_rows.append(
            {
                "id": artist_id,
                "name": name,
                "popularity": popularity,
                "genres": genres,
                "fallback": None,
            }
        )

    if not out_rows:
        return None

    return _standardize_schema(pl.DataFrame(out_rows))


def _decode_sqlite_text(value: object) -> str:
    """Decode sqlite text values safely, replacing malformed UTF-8 bytes."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess external genre sources into standardized parquet files."
    )
    source_choices = [source.name for source in get_genre_sources()]
    parser.add_argument(
        "--source",
        nargs="*",
        choices=source_choices,
        help="Sources to process (default: all)",
    )
    args = parser.parse_args()

    GENRE_DIR.mkdir(parents=True, exist_ok=True)

    processors = {
        "serkan": preprocess_serkan,
        "yamac": preprocess_yamac,
        "vectorql": preprocess_vectorql,
        "malte": preprocess_malte,
    }
    outputs = {
        "serkan": SERKAN_GENRE,
        "yamac": YAMAC_GENRE,
        "vectorql": VECTORQL_GENRE,
        "malte": MALTE_GENRE,
    }

    sources = args.source or [source.name for source in get_genre_sources()]

    for name in sources:
        print(f"\n--- {name} ---")
        processor = processors[name]
        output_path = outputs[name]
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
