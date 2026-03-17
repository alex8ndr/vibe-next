#!/usr/bin/env python3
"""
Run the dataset pipeline: filter -> process.

Usage:
    # Filter + process with defaults
    python run_pipeline.py

    # Unified dataset selection: pick specific datasets by name
    python run_pipeline.py --datasets data yamac_tracks

    # Use all available datasets (core + external)
    python run_pipeline.py --all-datasets

    # Use all except the original dataset
    python run_pipeline.py --all-datasets --exclude-datasets data
"""
import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
PIPELINE_DIR = SCRIPTS_DIR / "pipeline"

# Import paths for proper path resolution
sys.path.insert(0, str(SCRIPTS_DIR))
from paths import (
    FILTERED_DATASET,
    TRACKS_DATASET,
    ARTISTS_DATASET,
    get_input_dataset,
    get_all_track_datasets,
    get_added_artists,
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
        description="Run the dataset pipeline (filter -> process)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--process-only",
        action="store_true",
        help="Deprecated no-op: filter+process is now the default and only behavior",
    )
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
        "--keep-live",
        action="store_true",
        help="Keep live tracks (filter step only)",
    )
    parser.add_argument(
        "--max-international-pct",
        type=float,
        default=None,
        help="Maximum percentage of non-English tracks after language resolution (process step only)",
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
    parser.add_argument(
        "--subprocess",
        action="store_true",
        help="Use subprocess mode: write intermediate files to disk (legacy behavior)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()

    # Determine input file and merge paths based on dataset selection mode
    if args.datasets or args.all_datasets:
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
            exclude = set(args.exclude_datasets or [])
            selected_names = [n for n in available if n not in exclude]
            selected_paths = [available[n] for n in selected_names]

        if not selected_paths:
            print("Error: No datasets selected.")
            sys.exit(1)

        print(f"Datasets: {', '.join(selected_names)}")
        input_file = selected_paths[0]
        merge_paths = selected_paths[1:]
    else:
        try:
            input_file = get_input_dataset()
        except FileNotFoundError:
            print("Error: No input dataset found. Run convert_to_parquet.py first.")
            sys.exit(1)

        merge_paths = []
        added = get_added_artists()
        if added:
            merge_paths.append(added)

    added_artists_path = get_added_artists()

    if args.subprocess:
        if not args.skip_filter:
            filter_args = ["-i", str(input_file), "-o", str(FILTERED_DATASET)]
            if merge_paths:
                filter_args.append("--merge")
                filter_args.extend(str(p) for p in merge_paths)
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
            if args.keep_live:
                filter_args.append("--keep-live")
            if args.dry_run:
                filter_args.append("--dry-run")

            ret = run_script(PIPELINE_DIR / "filter_data.py", filter_args)
            if ret != 0:
                print(f"\nfilter_data.py failed with exit code {ret}")
                sys.exit(ret)

        if args.dry_run:
            print("\n[DRY-RUN] Skipping process step")
            return

        if not args.skip_process:
            process_args = [
                "-i", str(FILTERED_DATASET),
                "--tracks-output", str(TRACKS_DATASET),
                "--artists-output", str(ARTISTS_DATASET),
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
            if args.max_international_pct is not None:
                process_args.extend(["--max-international-pct", str(args.max_international_pct)])
            ret = run_script(PIPELINE_DIR / "process_data.py", process_args)
            if ret != 0:
                print(f"\nprocess_data.py failed with exit code {ret}")
                sys.exit(ret)
    else:
        # Default in-memory mode: no intermediate files written to disk
        from pipeline.filter_data import filter_data as _run_filter
        from pipeline.process_data import process_data as _run_process

        if not args.skip_filter:
            print("\nRunning filter_data (in-memory)...")
            print("=" * 60)
            stats, filtered_df = _run_filter(
                input_path=input_file,
                output_path=None,
                keep_remixes=args.keep_remixes,
                keep_live=args.keep_live,
                min_songs=args.min_songs if args.min_songs is not None else 2,
                verbose=args.verbose,
                merge_paths=merge_paths or None,
                enrich=not args.no_enrich,
                override=args.override_genres,
                override_only=args.override_genres_only,
                added_artists_path=added_artists_path,
            )
            print("=" * 60)
            print(f"Filtered: {stats['original_tracks']:,} -> {stats['final_tracks']:,} tracks")
        else:
            from io_utils import read_input_file
            filtered_df = read_input_file(FILTERED_DATASET)
            print(f"Loaded existing filtered data: {len(filtered_df):,} tracks")

        if args.dry_run:
            print("\n[DRY-RUN] Skipping process step")
            return

        if not args.skip_process:
            print("\nRunning process_data (in-memory)...")
            print("=" * 60)
            _run_process(
                input_path=None,
                tracks_output_path=TRACKS_DATASET,
                artists_output_path=ARTISTS_DATASET,
                max_songs=args.max_songs,
                max_artists=args.max_artists,
                max_international_pct=args.max_international_pct,
                smear_strength=args.smear_strength,
                verbose=args.verbose,
                dev=args.dev,
                input_df=filtered_df,
            )
            print("=" * 60)
    
    print("\nPipeline complete!")


if __name__ == "__main__":
    main()
