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

    # Merge all available external datasets during filtering
    python run_pipeline.py --process-only --include-external

    # Merge a specific external dataset during filtering
    python run_pipeline.py --process-only --external yamac

    # Unified dataset selection: pick specific datasets by name
    python run_pipeline.py --process-only --datasets data yamac_tracks

    # Use all available datasets (core + external)
    python run_pipeline.py --process-only --all-datasets

    # Use all except the original dataset
    python run_pipeline.py --process-only --all-datasets --exclude-datasets data

    # Incremental update only (fastest, lowest memory)
    python run_pipeline.py --incremental
    
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

# Import paths for proper path resolution
sys.path.insert(0, str(SCRIPTS_DIR))
from paths import (
    RAW_DATASET, RAW_CSV_ZIP,
    FILTERED_DATASET, FILTERED_CSV_ZIP,
    ADDED_ARTISTS, ADDED_ARTISTS_CSV_ZIP,
    ENCODED_DATASET,
    EXTERNAL_TRACK_DATASETS,
    get_external_track_datasets,
    get_input_dataset,
    get_all_track_datasets,
)


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
    
    # Incremental can be combined with add options
    parser.add_argument("--incremental", action="store_true", 
                        help="Use incremental update instead of full reprocess (faster, lower memory)")
    
    parser.add_argument("--limit", type=int, default=15, help="Max tracks per artist")
    parser.add_argument("--genre", help="Override genre")
    parser.add_argument("--expand", type=int, nargs="?", const=5, help="Expand to N similar artists")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("--skip-filter", action="store_true", help="Skip filter_data.py step")
    parser.add_argument("--skip-process", action="store_true", help="Skip process_data.py step")
    parser.add_argument(
        "--override-genres",
        action="store_true",
        help="Override existing genres with external data (filter step only)",
    )
    parser.add_argument(
        "--override-genres-only",
        action="store_true",
        help="Use only external genre matches and drop everything else (filter step only)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip external artist genre enrichment (filter step only)",
    )
    parser.add_argument(
        "--min-songs",
        type=int,
        default=None,
        help="Minimum songs per artist (filter step only)",
    )
    parser.add_argument(
        "--keep-remixes",
        action="store_true",
        help="Keep remix tracks (filter step only)",
    )
    parser.add_argument(
        "--max-international-pct",
        type=float,
        default=None,
        help="Maximum percentage of international tracks (filter step only)",
    )
    parser.add_argument(
        "--include-external",
        action="store_true",
        help="Merge all available external datasets from data/external",
    )
    parser.add_argument(
        "--external",
        action="append",
        help=(
            "Merge specific external dataset(s) by name. "
            "Available: " + ", ".join(sorted(EXTERNAL_TRACK_DATASETS.keys()))
        ),
    )
    parser.add_argument(
        "--exclude-external",
        action="append",
        help="Exclude specific external dataset(s) by name when using --include-external",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        help=(
            "Select specific datasets by name (unified selection). "
            "Available: " + ", ".join(sorted(get_all_track_datasets().keys()))
        ),
    )
    parser.add_argument(
        "--all-datasets",
        action="store_true",
        help="Include all available datasets (core + external)",
    )
    parser.add_argument(
        "--exclude-datasets",
        nargs="+",
        help="Exclude specific datasets by name (use with --all-datasets)",
    )
    parser.add_argument("--dev", action="store_true", help="Dev mode: fast compression for quicker processing")
    parser.add_argument(
        "--max-artists",
        type=int,
        default=0,
        help="Keep only the top N most popular artists (process step only)",
    )
    parser.add_argument(
        "--max-songs",
        type=int,
        default=50,
        help="Maximum songs per artist (process step only)",
    )
    parser.add_argument(
        "--smear-strength",
        type=float,
        default=0.6,
        help="Strength of inter-artist genre smearing 0.0-1.0 (process step only)",
    )
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
    
    # Step 2: Process the data
    if args.incremental:
        # Incremental mode: use incremental_update.py (fastest, lowest memory)
        inc_args = []
        if args.dry_run:
            inc_args.append("--dry-run")
        if args.verbose:
            inc_args.append("--verbose")
        
        ret = run_script(SCRIPTS_DIR / "incremental_update.py", inc_args, args.dry_run)
        if ret != 0:
            print(f"\nincremental_update.py failed with exit code {ret}")
            sys.exit(ret)
    else:
        # Full reprocess mode
        # Determine input file and merge files based on dataset selection mode
        if args.datasets or args.all_datasets:
            # Unified dataset selection
            available = get_all_track_datasets()
            if args.datasets:
                selected_names = []
                selected_paths = []
                for name in args.datasets:
                    if name not in available:
                        print(f"Unknown dataset: {name}")
                        print("Available:", ", ".join(sorted(available.keys())))
                        sys.exit(1)
                    selected_names.append(name)
                    selected_paths.append(available[name])
            else:
                # --all-datasets
                exclude = set(args.exclude_datasets or [])
                selected_names = [n for n in available if n not in exclude]
                selected_paths = [available[n] for n in selected_names]

            if not selected_paths:
                print("Error: No datasets selected.")
                sys.exit(1)

            print(f"Datasets: {', '.join(selected_names)}")
            input_file = selected_paths[0]
            unified_merge = [str(p) for p in selected_paths[1:]]
        else:
            # Default behavior (backward compatible)
            try:
                input_file = get_input_dataset()
            except FileNotFoundError:
                print("Error: No input dataset found. Run convert_to_parquet.py first.")
                sys.exit(1)
            unified_merge = None
        
        # Step 2a: Filter data
        if not args.skip_filter:
            filter_args = [
                "-i", str(input_file),
                "-o", str(FILTERED_DATASET),
            ]

            if unified_merge is not None:
                # Unified mode: merge files already determined
                merge_files = unified_merge
            else:
                # Legacy mode: auto-merge added_artists + optional external
                merge_files = []
                if ADDED_ARTISTS.exists():
                    merge_files.append(str(ADDED_ARTISTS))
                elif ADDED_ARTISTS_CSV_ZIP.exists():
                    merge_files.append(str(ADDED_ARTISTS_CSV_ZIP))

                external_paths = []
                available = get_external_track_datasets()
                if args.include_external:
                    exclude_names = set(args.exclude_external or [])
                    external_paths = [p for name, p in available.items() if p.exists() and name not in exclude_names]
                elif args.external:
                    for name in args.external:
                        if name not in available:
                            print(f"Unknown external dataset: {name}")
                            print("Available:", ", ".join(sorted(available.keys())))
                            sys.exit(1)
                        path = available[name]
                        if path.exists():
                            external_paths.append(path)
                        else:
                            print(f"External dataset not found: {path}")

                merge_files.extend([str(p) for p in external_paths])

            if merge_files:
                filter_args.append("--merge")
                filter_args.extend(merge_files)

            if args.verbose:
                filter_args.append("--verbose")
            if args.override_genres:
                filter_args.append("--override-genres")
            if args.override_genres_only:
                filter_args.append("--override-genres-only")
            if args.no_enrich:
                filter_args.append("--no-enrich")
            if args.min_songs is not None:
                filter_args.extend(["--min-songs", str(args.min_songs)])
            if args.keep_remixes:
                filter_args.append("--keep-remixes")
            if args.max_international_pct is not None:
                filter_args.extend(["--max-international-pct", str(args.max_international_pct)])
            
            ret = run_script(PIPELINE_DIR / "filter_data.py", filter_args)
            if ret != 0:
                print(f"\nfilter_data.py failed with exit code {ret}")
                sys.exit(ret)
        
        # Step 2b: Process data
        if not args.skip_process:
            process_args = [
                "-i", str(FILTERED_DATASET),
                "-o", str(ENCODED_DATASET),
            ]
            if args.verbose:
                process_args.append("--verbose")
            if args.dev:
                process_args.append("--dev")
            if args.max_artists > 0:
                process_args.extend(["--max-artists", str(args.max_artists)])
            if args.max_songs != 50:
                process_args.extend(["--max-songs", str(args.max_songs)])
            if args.smear_strength != 0.6:
                process_args.extend(["--smear-strength", str(args.smear_strength)])
            
            ret = run_script(PIPELINE_DIR / "process_data.py", process_args)
            if ret != 0:
                print(f"\nprocess_data.py failed with exit code {ret}")
                sys.exit(ret)
    
    print("\nPipeline complete!")


if __name__ == "__main__":
    main()
