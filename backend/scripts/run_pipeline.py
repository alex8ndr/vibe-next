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
)
from pipeline.utils.dataset_resolver import (
    resolve_filter_inputs,
    add_dataset_selection_args,
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
        "--preserve-genres",
        action="store_true",
        help="Keep original genres instead of overriding with external data (filter step only)",
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
        "--english-pct",
        type=float,
        default=75.0,
        help="Target English percentage after language shaping (process step only)",
    )
    parser.add_argument(
        "--no-shaping",
        action="store_true",
        help="Disable language shaping entirely (process step only)",
    )
    parser.add_argument(
        "--min-lang-artists",
        type=int,
        default=100,
        help="Drop non-English languages with fewer than N artists (process step only)",
    )
    add_dataset_selection_args(parser)
    parser.add_argument("--dev", action="store_true", help="Dev mode: fast compression for quicker processing")
    parser.add_argument(
        "--max-artists",
        type=int,
        default=0,
        help="Keep only the top N most popular artists (process step only)",
    )
    parser.add_argument(
        "--cap",
        type=int,
        default=50,
        help="Maximum songs for the most popular artists (process step only)",
    )
    parser.add_argument(
        "--floor",
        type=int,
        default=20,
        help="Maximum songs for the least popular artists (process step only)",
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

    # Resolve datasets via shared resolver
    try:
        resolution = resolve_filter_inputs(
            datasets=args.datasets,
            all_datasets=args.all_datasets,
            exclude_datasets=args.exclude_datasets,
            primary_dataset=args.primary_dataset,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    input_file = resolution.input_path
    merge_paths = resolution.merge_paths
    added_artists_path = resolution.added_artists_path

    print(f"Primary dataset: {resolution.primary_name} ({input_file.name})")
    if merge_paths:
        merge_names = [p.stem for p in merge_paths]
        print(f"Merge datasets: {', '.join(merge_names)}")

    if args.subprocess:
        if not args.skip_filter:
            filter_args = ["-i", str(input_file), "-o", str(FILTERED_DATASET)]
            if merge_paths:
                filter_args.append("--merge")
                filter_args.extend(str(p) for p in merge_paths)
            if args.verbose:
                filter_args.append("--verbose")
            if args.preserve_genres:
                filter_args.append("--preserve-genres")
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
            if args.cap != 50:
                process_args.extend(["--cap", str(args.cap)])
            if args.floor != 20:
                process_args.extend(["--floor", str(args.floor)])
            if args.smear_strength != 0.6:
                process_args.extend(["--smear-strength", str(args.smear_strength)])
            if args.english_pct != 75.0:
                process_args.extend(["--english-pct", str(args.english_pct)])
            if args.no_shaping:
                process_args.append("--no-shaping")
            if args.min_lang_artists != 10:
                process_args.extend(["--min-lang-artists", str(args.min_lang_artists)])
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
                preserve_genres=args.preserve_genres,
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
                cap=args.cap,
                floor=args.floor,
                max_artists=args.max_artists,
                english_pct=args.english_pct,
                no_shaping=args.no_shaping,
                smear_strength=args.smear_strength,
                verbose=args.verbose,
                dev=args.dev,
                input_df=filtered_df,
                min_lang_artists=args.min_lang_artists,
            )
            print("=" * 60)
    
    print("\nPipeline complete!")


if __name__ == "__main__":
    main()
