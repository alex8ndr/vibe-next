#!/usr/bin/env python3
"""
Convert existing CSV/zip data files to parquet format.

Usage:
    python convert_to_parquet.py              # Convert all default files
    python convert_to_parquet.py -i data.csv.zip -o data.parquet  # Custom paths
"""

import argparse
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from paths import (
    DATA_DIR, 
    RAW_DATASET, 
    ADDED_ARTISTS,
    RAW_CSV_ZIP,
    ADDED_ARTISTS_CSV_ZIP,
)
from io_utils import atomic_write_parquet


def read_csv_zip(path: Path) -> pl.DataFrame:
    """Read CSV from a zip file (legacy format) using Polars."""
    with zipfile.ZipFile(path, 'r') as zf:
        # Assume single CSV file in zip
        csv_names = [n for n in zf.namelist() if n.endswith('.csv')]
        if not csv_names:
            raise ValueError(f"No CSV file found in {path}")
        
        csv_name = csv_names[0]
        with zf.open(csv_name) as f:
            content = f.read()
            return pl.read_csv(BytesIO(content), infer_schema_length=10000)


def convert_file(
    input_path: Path,
    output_path: Path,
    verbose: bool = False,
) -> bool:
    """Convert a single file to parquet using Polars."""
    if not input_path.exists():
        print(f"Warning: {input_path} not found, skipping")
        return False
    
    if input_path.suffix == '.zip' or str(input_path).endswith('.csv.zip'):
        print(f"Reading {input_path} (CSV in zip)...")
        df_pl = read_csv_zip(input_path)
    elif input_path.suffix == '.csv':
        print(f"Reading {input_path} (CSV)...")
        df_pl = pl.read_csv(input_path, infer_schema_length=10000)
    elif input_path.suffix == '.parquet':
        print(f"Skipping {input_path} (already parquet)")
        return False
    else:
        print(f"Warning: Unknown format for {input_path}, skipping")
        return False
    
    # Cast numeric columns to float32 for consistency
    for col in df_pl.columns:
        if df_pl[col].dtype == pl.Float64:
            df_pl = df_pl.with_columns(pl.col(col).cast(pl.Float32))
    
    print(f"Converting {len(df_pl):,} rows to parquet...")
    atomic_write_parquet(df_pl, output_path, verbose=verbose)
    print(f"[OK] Wrote {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert CSV data to Parquet")
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=None,
        help="Input CSV or zip file (default: convert all legacy files)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output parquet file",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    
    if args.input:
        if not args.output:
            print("Error: --output required when --input is specified")
            sys.exit(1)
        convert_file(args.input, args.output, args.verbose)
    else:
        # Convert all default files
        files_to_convert = [
            (RAW_CSV_ZIP, RAW_DATASET),
            (ADDED_ARTISTS_CSV_ZIP, ADDED_ARTISTS),
        ]
        
        converted = 0
        for input_path, output_path in files_to_convert:
            if convert_file(input_path, output_path, args.verbose):
                converted += 1
        
        print(f"\nConverted {converted} file(s)")
        
        if converted > 0:
            print("\nNext steps:")
            print("  1. Verify the parquet files are correct")
            print("  2. You can remove the old .csv.zip files if desired")
            print("  3. Run: python pipeline/filter_data.py")


if __name__ == "__main__":
    main()
