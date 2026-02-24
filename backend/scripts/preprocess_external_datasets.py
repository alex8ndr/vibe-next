#!/usr/bin/env python3
"""
Preprocess external CSV datasets into trimmed parquet files for merging.

The output parquet files keep only rows with required fields and map columns
into the pipeline's raw schema. This makes it easy to merge additional tracks
via process_data.py --merge without pulling in unusable rows.

Usage:
    python preprocess_external_datasets.py
    python preprocess_external_datasets.py --dataset yamac
    python preprocess_external_datasets.py --output-dir backend/data/external
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from io_utils import atomic_write_parquet
from paths import DATA_DIR
from schema import RAW_COLUMN_ORDER, coerce_to_schema

REQUIRED_COLUMNS = [
    "track_id",
    "track_name",
    "artist_name",
    "popularity",
    "danceability",
    "energy",
    "acousticness",
    "instrumentalness",
    "liveness",
    "speechiness",
    "tempo",
    "valence",
]


def normalize_string_expr(col: str) -> pl.Expr:
    base = pl.col(col).cast(pl.Utf8).str.strip_chars()
    return pl.when(base == "").then(None).otherwise(base)


def parse_list_string_expr(col: str) -> pl.Expr:
    base = (
        pl.col(col)
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.replace_all(r"^\s*\[|\]\s*$", "")
        .str.replace_all(r"[\"']", "")
        .str.replace_all(r"&|;", ",")
    )
    first = base.str.split(",").list.get(0).str.strip_chars()
    return pl.when(first == "").then(None).otherwise(first)


def parse_year_expr(col: str) -> pl.Expr:
    year = pl.col(col).cast(pl.Utf8).str.slice(0, 4)
    return pl.when(year == "").then(None).otherwise(year).cast(pl.Int64)


def build_dataset(df: pl.DataFrame, mapping: dict[str, pl.Expr]) -> pl.DataFrame:
    expressions = []
    for col in RAW_COLUMN_ORDER:
        expr = mapping.get(col, pl.lit(None).alias(col))
        expressions.append(expr.alias(col))

    df = df.select(expressions)
    df = coerce_to_schema(df)

    required_filters = []
    for col in REQUIRED_COLUMNS:
        if col in df.columns:
            required_filters.append(pl.col(col).is_not_null())

    if required_filters:
        combined = required_filters[0]
        for expr in required_filters[1:]:
            combined &= expr
        df = df.filter(combined)

    return df


def preprocess_dataset(input_path: Path, output_path: Path, mapping: dict[str, pl.Expr]) -> None:
    print(f"Reading {input_path}...")
    df = pl.read_csv(input_path, infer_schema_length=10000)
    df_out = build_dataset(df, mapping)
    print(f"  Rows: {len(df_out):,} (from {len(df):,})")
    atomic_write_parquet(df_out, output_path, compression="zstd", compression_level=12)
    print(f"  Wrote {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preprocess external datasets into trimmed parquet files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        action="append",
        choices=["archive", "bruce", "yamac", "anant", "serkan"],
        help="Dataset(s) to process (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATA_DIR / "external",
        help="Output directory for parquet files",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = {
        "archive": {
            "input": DATA_DIR / "archive (3)" / "data.csv",
            "output": output_dir / "archive_3.parquet",
            "mapping": {
                "track_id": normalize_string_expr("id"),
                "track_name": normalize_string_expr("name"),
                "artist_name": parse_list_string_expr("artists"),
                "genre": pl.lit(None),
                "year": pl.col("year"),
                "popularity": pl.col("popularity"),
                "duration_ms": pl.col("duration_ms"),
                "danceability": pl.col("danceability"),
                "energy": pl.col("energy"),
                "key": pl.col("key"),
                "loudness": pl.col("loudness"),
                "mode": pl.col("mode"),
                "speechiness": pl.col("speechiness"),
                "acousticness": pl.col("acousticness"),
                "instrumentalness": pl.col("instrumentalness"),
                "liveness": pl.col("liveness"),
                "valence": pl.col("valence"),
                "tempo": pl.col("tempo"),
            },
        },
        "bruce": {
            "input": DATA_DIR / "bruce-spotify" / "Spotify.csv",
            "output": output_dir / "bruce_spotify.parquet",
            "mapping": {
                "track_id": normalize_string_expr("id"),
                "track_name": normalize_string_expr("name"),
                "artist_name": parse_list_string_expr("artists"),
                "genre": pl.lit(None),
                "year": pl.col("year"),
                "popularity": pl.col("popularity"),
                "duration_ms": pl.col("duration_ms"),
                "danceability": pl.col("danceability"),
                "energy": pl.col("energy"),
                "key": pl.col("key"),
                "loudness": pl.col("loudness"),
                "mode": pl.col("mode"),
                "speechiness": pl.col("speechiness"),
                "acousticness": pl.col("acousticness"),
                "instrumentalness": pl.col("instrumentalness"),
                "liveness": pl.col("liveness"),
                "valence": pl.col("valence"),
                "tempo": pl.col("tempo"),
            },
        },
        "yamac": {
            "input": DATA_DIR / "yamac-spotify-1920-2020" / "tracks.csv",
            "output": output_dir / "yamac_tracks.parquet",
            "mapping": {
                "track_id": normalize_string_expr("id"),
                "track_name": normalize_string_expr("name"),
                "artist_name": parse_list_string_expr("artists"),
                "genre": pl.lit(None),
                "year": parse_year_expr("release_date"),
                "popularity": pl.col("popularity"),
                "duration_ms": pl.col("duration_ms"),
                "danceability": pl.col("danceability"),
                "energy": pl.col("energy"),
                "key": pl.col("key"),
                "loudness": pl.col("loudness"),
                "mode": pl.col("mode"),
                "speechiness": pl.col("speechiness"),
                "acousticness": pl.col("acousticness"),
                "instrumentalness": pl.col("instrumentalness"),
                "liveness": pl.col("liveness"),
                "valence": pl.col("valence"),
                "tempo": pl.col("tempo"),
                "time_signature": pl.col("time_signature"),
            },
        },
        "anant": {
            "input": DATA_DIR / "anant-almost-million" / "tracks.csv",
            "output": output_dir / "anant_tracks.parquet",
            "mapping": {
                "track_id": normalize_string_expr("track_id"),
                "track_name": normalize_string_expr("name"),
                "artist_name": parse_list_string_expr("track_artists"),
                "genre": parse_list_string_expr("genres"),
                "popularity": pl.col("popularity"),
                "danceability": pl.col("danceability"),
                "energy": pl.col("energy"),
                "key": pl.col("key"),
                "mode": pl.col("mode"),
                "speechiness": pl.col("speechiness"),
                "acousticness": pl.col("acousticness"),
                "instrumentalness": pl.col("instrumentalness"),
                "liveness": pl.col("liveness"),
                "valence": pl.col("valence"),
                "tempo": pl.col("tempo"),
                "time_signature": pl.col("time_signature"),
            },
        },
        "serkan": {
            "input": DATA_DIR / "external" / "serkan-550k-spotify" / "songs.csv",
            "output": output_dir / "serkan_tracks.parquet",
            "mapping": {
                "track_id": normalize_string_expr("id"),
                "track_name": normalize_string_expr("name"),
                "artist_name": parse_list_string_expr("artists"),
                "genre": normalize_string_expr("genre"),
                "year": pl.col("year"),
                "popularity": pl.col("popularity"),
                "duration_ms": pl.col("duration_ms"),
                "danceability": pl.col("danceability"),
                "energy": pl.col("energy"),
                "key": pl.col("key"),
                "loudness": pl.col("loudness"),
                "mode": pl.col("mode"),
                "speechiness": pl.col("speechiness"),
                "acousticness": pl.col("acousticness"),
                "instrumentalness": pl.col("instrumentalness"),
                "liveness": pl.col("liveness"),
                "valence": pl.col("valence"),
                "tempo": pl.col("tempo"),
            },
        },
    }

    selected = args.dataset or list(datasets.keys())
    for key in selected:
        config = datasets[key]
        if not config["input"].exists():
            print(f"Missing {config['input']}, skipping")
            continue
        preprocess_dataset(config["input"], config["output"], config["mapping"])


if __name__ == "__main__":
    main()
