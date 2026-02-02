#!/usr/bin/env python3
"""
Run the full discovery pipeline: add artists → filter → process.

Usage:
    # Add artists interactively, then process
    python run_pipeline.py
    
    # Add specific artists, then process
    python run_pipeline.py --names "Radiohead, Coldplay"
    
    # Add from URL, then process
    python run_pipeline.py --url "https://open.spotify.com/album/xxx"
    
    # Skip add step, just run filter + process
    python run_pipeline.py --process-only
    
    # Dry-run: preview changes without saving
    python run_pipeline.py --names "Radiohead" --dry-run
"""
import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
DISCOVERY_DIR = SCRIPTS_DIR / "discovery"
PIPELINE_DIR = SCRIPTS_DIR / "pipeline"
DATA_DIR = SCRIPTS_DIR.parent / "data"

# Data file paths
DATA_CSV = DATA_DIR / "data.csv.zip"
DATA_FILTERED_CSV = DATA_DIR / "data_filtered.csv.zip"
ADDED_ARTISTS_CSV = DATA_DIR / "added_artists.csv.zip"
DATA_ENCODED_PARQUET = DATA_DIR / "data_encoded.parquet"


def run_script(script_path: Path, args: list[str], dry_run: bool = False) -> int:
    """Run a Python script with arguments."""
    cmd = [sys.executable, str(script_path)] + args
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Running: {' '.join(cmd)}\n")
    print("=" * 60)
    result = subprocess.run(cmd)
    print("=" * 60)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Run the full discovery pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    # Add artist options (passed through to add_artist.py)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--track", help="Spotify track URL")
    group.add_argument("--album", help="Spotify album URL")
    group.add_argument("--url", help="Spotify URL (auto-detect track/album)")
    group.add_argument("--file", help="File with Spotify URLs")
    group.add_argument("--names", help="Comma-separated artist names")
    group.add_argument("--process-only", action="store_true", help="Skip add step, just filter + process")
    
    parser.add_argument("--limit", type=int, default=15, help="Max tracks per artist")
    parser.add_argument("--genre", help="Override genre")
    parser.add_argument("--expand", type=int, nargs="?", const=5, help="Expand to N similar artists")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("--skip-filter", action="store_true", help="Skip filter_data.py step")
    parser.add_argument("--skip-process", action="store_true", help="Skip process_data.py step")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    # Step 1: Add artists (unless --process-only)
    if not args.process_only:
        add_args = []
        
        if args.track:
            add_args.extend(["--track", args.track])
        elif args.album:
            add_args.extend(["--album", args.album])
        elif args.url:
            add_args.extend(["--url", args.url])
        elif args.file:
            add_args.extend(["--file", args.file])
        elif args.names:
            add_args.extend(["--names", args.names])
        # else: interactive mode
        
        add_args.extend(["--limit", str(args.limit)])
        
        if args.genre:
            add_args.extend(["--genre", args.genre])
        if args.expand:
            add_args.extend(["--expand", str(args.expand)])
        if args.dry_run:
            add_args.append("--dry-run")
        if args.verbose:
            add_args.append("--verbose")
        
        ret = run_script(DISCOVERY_DIR / "add_artist.py", add_args, args.dry_run)
        if ret != 0:
            print(f"\nadd_artist.py failed with exit code {ret}")
            sys.exit(ret)
        
        if args.dry_run:
            print("\n[DRY-RUN] Skipping filter + process steps")
            return
    
    # Step 2: Filter data
    if not args.skip_filter:
        filter_args = [
            "-i", str(DATA_CSV),
            "-o", str(DATA_FILTERED_CSV),
        ]
        if args.verbose:
            filter_args.append("--verbose")
        
        ret = run_script(PIPELINE_DIR / "filter_data.py", filter_args)
        if ret != 0:
            print(f"\nfilter_data.py failed with exit code {ret}")
            sys.exit(ret)
    
    # Step 3: Process data
    if not args.skip_process:
        process_args = [
            "-i", str(DATA_FILTERED_CSV),
            "-o", str(DATA_ENCODED_PARQUET),
        ]
        if ADDED_ARTISTS_CSV.exists():
            process_args.extend(["--merge", str(ADDED_ARTISTS_CSV)])
        if args.verbose:
            process_args.append("--verbose")
        
        ret = run_script(PIPELINE_DIR / "process_data.py", process_args)
        if ret != 0:
            print(f"\nprocess_data.py failed with exit code {ret}")
            sys.exit(ret)
    
    print("\n✓ Pipeline complete!")


if __name__ == "__main__":
    main()
