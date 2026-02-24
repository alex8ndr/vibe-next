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
    python preprocess_external_datasets.py --auto --input path/to/data.csv --output-name my_dataset
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

# Variants for auto-inference (target_col -> list of possible source names, lowercase)
_COLUMN_VARIANTS: dict[str, list[str]] = {
    "track_id": ["id", "track_id", "spotify_id", "uri"],
    "track_name": ["name", "track_name", "title", "song_name", "song"],
    "artist_name": ["artists", "artist_name", "artist", "artist_names"],
    "genre": ["genre", "genres", "track_genre"],
    "year": ["year", "release_date", "release_year"],
    "popularity": ["popularity"],
    "duration_ms": ["duration_ms", "duration"],
    "danceability": ["danceability"],
    "energy": ["energy"],
    "key": ["key"],
    "loudness": ["loudness"],
    "mode": ["mode"],
    "speechiness": ["speechiness"],
    "acousticness": ["acousticness"],
    "instrumentalness": ["instrumentalness"],
    "liveness": ["liveness"],
    "valence": ["valence"],
    "tempo": ["tempo"],
    "time_signature": ["time_signature"],
}

# Columns where array-like values should be parsed with parse_list_string_expr
_LIST_COLUMNS = {"artist_name", "genre"}

# Columns where date-like values should be parsed with parse_year_expr
_YEAR_COLUMNS = {"year"}


def _looks_like_list_string(series: pl.Series) -> bool:
    """Check if the first non-null value looks like a Python list string."""
    non_null = series.drop_nulls()
    if len(non_null) == 0:
        return False
    first = str(non_null[0]).strip()
    return first.startswith("[")


def _looks_like_date_string(series: pl.Series) -> bool:
    """Check if values look like dates (e.g. '2020-01-15') rather than plain years."""
    non_null = series.drop_nulls()
    if len(non_null) == 0:
        return False
    first = str(non_null[0]).strip()
    return len(first) > 4 and "-" in first


def infer_column_mapping(df: pl.DataFrame) -> dict[str, pl.Expr]:
    """Auto-infer a column mapping from a DataFrame based on common name variants.

    Uses case-insensitive matching against known column name patterns.
    For array-like columns (artists, genres), detects Python list strings
    and uses parse_list_string_expr accordingly.
    For year-like columns with date strings, uses parse_year_expr.
    """
    # Build a lowercase -> original-name lookup
    lower_to_orig = {c.lower(): c for c in df.columns}
    mapping: dict[str, pl.Expr] = {}

    for target, variants in _COLUMN_VARIANTS.items():
        # Find the first matching variant (case-insensitive)
        matched_orig = None
        for variant in variants:
            if variant in lower_to_orig:
                matched_orig = lower_to_orig[variant]
                break
        if matched_orig is None:
            continue

        # Decide how to build the expression
        if target in _LIST_COLUMNS and _looks_like_list_string(df[matched_orig]):
            mapping[target] = parse_list_string_expr(matched_orig)
        elif target in _YEAR_COLUMNS and _looks_like_date_string(df[matched_orig]):
            mapping[target] = parse_year_expr(matched_orig)
        elif target in ("track_id", "track_name") or target in _LIST_COLUMNS:
            mapping[target] = normalize_string_expr(matched_orig)
        else:
            mapping[target] = pl.col(matched_orig)

    return mapping


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
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-infer column mapping from an arbitrary CSV",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Input CSV path (required with --auto)",
    )
    parser.add_argument(
        "--output-name",
        type=str,
        help="Stem name for the output parquet file (required with --auto)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.auto:
        if not args.input or not args.output_name:
            print("Error: --auto requires both --input and --output-name", file=sys.stderr)
            sys.exit(1)
        input_path = args.input
        if not input_path.exists():
            print(f"Error: {input_path} not found", file=sys.stderr)
            sys.exit(1)
        print(f"Reading {input_path} for auto-inference...")
        df = pl.read_csv(input_path, infer_schema_length=10000)
        mapping = infer_column_mapping(df)
        print(f"  Inferred mappings: {', '.join(sorted(mapping.keys()))}")
        output_path = output_dir / f"{args.output_name}.parquet"
        df_out = build_dataset(df, mapping)
        print(f"  Rows: {len(df_out):,} (from {len(df):,})")
        atomic_write_parquet(df_out, output_path, compression="zstd", compression_level=12)
        print(f"  Wrote {output_path}")
        return

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
