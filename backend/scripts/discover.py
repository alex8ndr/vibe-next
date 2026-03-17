#!/usr/bin/env python3
"""
Unified discovery entry point for Vibe data pipeline.

Consolidates all discovery operations into a single CLI:
- add: Add specific artists by name, track URL, or album URL
- trending: Add artists from current music charts
- expand: Discover related artists via Last.fm
- backfill: Fill in missing albums for existing artists
- albums: Check a specific artist for new albums (alias for backfill --artist)

Examples:
    # Add specific artists
    python discover.py add "Radiohead, Coldplay" --update
    
    # Add from Spotify URL
    python discover.py add --url "https://open.spotify.com/album/xxx" --update
    
    # Add trending chart artists
    python discover.py trending --update --max-add 15
    
    # Discover similar artists
    python discover.py expand --seeds "Radiohead" --update
    
    # Backfill missing albums for low-track-count artists
    python discover.py backfill --update --limit 50
    
    # Check specific artist for new albums
    python discover.py albums "Radiohead" --update

Common flags for all commands:
    --update      Actually save changes (dry-run by default)
    -v, --verbose Print detailed progress
    --limit       Control how many artists/tracks to process
    --tracks      Set tracks per artist (default: 15)
"""
import argparse
import subprocess
import sys
from pathlib import Path

DISCOVERY_DIR = Path(__file__).parent / "discovery"

# Import centralized defaults
sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    DEFAULT_TRACKS_PER_ARTIST,
    DEFAULT_MAX_ADD,
    DEFAULT_MIN_TRACKS,
    DEFAULT_MIN_MATCH,
    DEFAULT_BACKFILL_LIMIT,
    DEFAULT_EXPAND_LIMIT,
    DEFAULT_TRENDING_LIMIT,
    DEFAULT_DIVERSITY_WEIGHT,
)


def run_script(script_name: str, args: list[str], verbose: bool = False) -> int:
    """Run a discovery script with arguments."""
    script_path = DISCOVERY_DIR / script_name
    cmd = [sys.executable, str(script_path)] + args
    
    if verbose:
        print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd)
    return result.returncode


def add_args_to_parser(parser: argparse.ArgumentParser, include_tracks: bool = True):
    """Add common arguments to a subparser."""
    parser.add_argument(
        "--update", action="store_true",
        help="Actually save changes (dry-run by default)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print detailed progress"
    )
    if include_tracks:
        parser.add_argument(
            "--tracks", type=int, default=DEFAULT_TRACKS_PER_ARTIST,
            help=f"Tracks per artist (default: {DEFAULT_TRACKS_PER_ARTIST})"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Unified discovery for Vibe dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  discover.py add "Radiohead, Bjork" --update
  discover.py add --url "https://open.spotify.com/album/xxx" --update
  discover.py trending --update --max-add 15
  discover.py expand --seeds "Radiohead" --limit 10 --update
  discover.py backfill --update --limit 50
  discover.py albums "Radiohead" --update"""
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Discovery operation")
    
    # ========================================================================
    # discover.py add [artists] [--url URL] [--track TRACK] [--album ALBUM]
    # ========================================================================
    add_parser = subparsers.add_parser(
        "add",
        help="Add specific artist(s) by name or Spotify URL",
        description="Add artists to the dataset. Supports names, track URLs, album URLs, or interactive mode."
    )
    add_parser.add_argument(
        "artists", nargs="?",
        help="Artist name(s), comma-separated (searches via Deezer)"
    )
    add_parser.add_argument(
        "--url",
        help="Spotify URL (auto-detects track or album)"
    )
    add_parser.add_argument(
        "--track",
        help="Spotify track ID or URL (fetches artist's top tracks)"
    )
    add_parser.add_argument(
        "--album",
        help="Spotify album ID or URL (fetches all album tracks)"
    )
    add_parser.add_argument(
        "--file",
        help="File with Spotify URLs/IDs (one per line)"
    )
    add_parser.add_argument(
        "--expand", type=int, nargs="?", const=5, default=None,
        help="Also add N similar artists via Last.fm (default: 5 if flag present)"
    )
    add_args_to_parser(add_parser)
    
    # ========================================================================
    # discover.py trending [--country COUNTRY] [--viral] [--max-add N]
    # ========================================================================
    trend_parser = subparsers.add_parser(
        "trending",
        help="Add artists from current music charts",
        description="Check trending artists from Spotify charts and add missing ones."
    )
    trend_parser.add_argument(
        "--country", default="global",
        help="Country code (us, gb, de, etc.) or 'global' (default: global)"
    )
    trend_parser.add_argument(
        "--viral", action="store_true",
        help="Use viral charts instead of top charts"
    )
    trend_parser.add_argument(
        "--max-add", type=int, default=DEFAULT_MAX_ADD,
        help=f"Max artists to add (default: {DEFAULT_MAX_ADD})"
    )
    trend_parser.add_argument(
        "--min-tracks", type=int, default=DEFAULT_MIN_TRACKS,
        help=f"Min tracks available to add artist (default: {DEFAULT_MIN_TRACKS})"
    )
    trend_parser.add_argument(
        "--detail", action="store_true",
        help="Show detailed info for each artist"
    )
    add_args_to_parser(trend_parser)
    
    # ========================================================================
    # discover.py expand [--seeds SEEDS] [--limit N] [--min-match SCORE]
    # ========================================================================
    expand_parser = subparsers.add_parser(
        "expand",
        help="Discover related artists via Last.fm",
        description="Expand from seed artists using Last.fm similar artist API."
    )
    expand_parser.add_argument(
        "artists", nargs="?",
        help="Seed artist name(s), comma-separated"
    )
    expand_parser.add_argument(
        "--seeds",
        help="Seed artist names (alternative to positional arg)"
    )
    expand_parser.add_argument(
        "--limit", type=int, default=DEFAULT_EXPAND_LIMIT,
        help=f"Max artists to discover (default: {DEFAULT_EXPAND_LIMIT})"
    )
    expand_parser.add_argument(
        "--min-match", type=float, default=DEFAULT_MIN_MATCH,
        help=f"Minimum Last.fm match score 0-1 (default: {DEFAULT_MIN_MATCH})"
    )
    expand_parser.add_argument(
        "--diversity", type=float, default=DEFAULT_DIVERSITY_WEIGHT,
        help=f"Track diversity weight 0-1 (default: {DEFAULT_DIVERSITY_WEIGHT})"
    )
    expand_parser.add_argument(
        "--infer-genre", action="store_true",
        help="Try to infer genre from related artists (slower)"
    )
    add_args_to_parser(expand_parser)
    
    # ========================================================================
    # discover.py backfill [--limit N] [--max-tracks N] [--all]
    # ========================================================================
    backfill_parser = subparsers.add_parser(
        "backfill",
        help="Backfill missing albums for existing artists",
        description="Check artists with few tracks for missing albums and add them."
    )
    backfill_parser.add_argument(
        "--limit", type=int, default=DEFAULT_BACKFILL_LIMIT,
        help=f"Max artists to check (default: {DEFAULT_BACKFILL_LIMIT})"
    )
    backfill_parser.add_argument(
        "--max-tracks", type=int,
        help="Only check artists with fewer than N tracks"
    )
    backfill_parser.add_argument(
        "--all", dest="check_all", action="store_true",
        help="Check all artists (ignores --limit)"
    )
    backfill_parser.add_argument(
        "--use-cache", action="store_true",
        help="Skip recently checked artists"
    )
    add_args_to_parser(backfill_parser, include_tracks=False)
    
    # ========================================================================
    # discover.py albums ARTIST [--update]
    # ========================================================================
    album_parser = subparsers.add_parser(
        "albums",
        help="Check specific artist for new albums",
        description="Check a single artist for albums not in the dataset."
    )
    album_parser.add_argument(
        "artist",
        help="Artist name or Spotify URL"
    )
    album_parser.add_argument(
        "--url", action="store_true",
        help="Treat artist as Spotify URL"
    )
    album_parser.add_argument(
        "--include-variants", action="store_true",
        help="Include remix/acoustic variants (skipped by default)"
    )
    add_args_to_parser(album_parser, include_tracks=False)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Convert args to script-specific arguments
    script_args = []
    
    if args.command == "add":
        # Route to add_artist.py
        if args.artists:
            script_args.extend(["--names", args.artists])
        elif args.url:
            script_args.extend(["--url", args.url])
        elif args.track:
            script_args.extend(["--track", args.track])
        elif args.album:
            script_args.extend(["--album", args.album])
        elif args.file:
            script_args.extend(["--file", args.file])
        # else: interactive mode (no args)
        
        if args.expand is not None:
            script_args.extend(["--expand", str(args.expand)])
        if args.tracks != DEFAULT_TRACKS_PER_ARTIST:
            script_args.extend(["--tracks", str(args.tracks)])
        if args.update:
            script_args.append("--update")
        if args.verbose:
            script_args.append("--verbose")
            
        exit_code = run_script("add_artist.py", script_args, args.verbose)
        
    elif args.command == "trending":
        # Route to check_trending.py
        if args.viral:
            script_args.append("--viral")
        if args.country != "global":
            script_args.extend(["--country", args.country])
        if args.max_add != DEFAULT_MAX_ADD:
            script_args.extend(["--max-add", str(args.max_add)])
        if args.min_tracks != DEFAULT_MIN_TRACKS:
            script_args.extend(["--min-tracks", str(args.min_tracks)])
        if args.detail:
            script_args.append("--detail")
        if args.tracks != DEFAULT_TRACKS_PER_ARTIST:
            script_args.extend(["--tracks", str(args.tracks)])
        if args.update:
            script_args.append("--update")
        if args.verbose:
            script_args.append("--verbose")
            
        exit_code = run_script("check_trending.py", script_args, args.verbose)
        
    elif args.command == "expand":
        # Route to expand_artists.py
        seeds = args.artists or args.seeds
        if seeds:
            script_args.extend(["--seeds", seeds])
        if args.limit != DEFAULT_EXPAND_LIMIT:
            script_args.extend(["--limit", str(args.limit)])
        if args.min_match != DEFAULT_MIN_MATCH:
            script_args.extend(["--min-match", str(args.min_match)])
        if args.tracks != DEFAULT_TRACKS_PER_ARTIST:
            script_args.extend(["--tracks", str(args.tracks)])
        if args.diversity != DEFAULT_DIVERSITY_WEIGHT:
            script_args.extend(["--diversity", str(args.diversity)])
        if args.infer_genre:
            script_args.append("--infer-genre")
        if args.update:
            script_args.append("--update")
        if args.verbose:
            script_args.append("--verbose")
            
        exit_code = run_script("expand_artists.py", script_args, args.verbose)
        
    elif args.command == "backfill":
        # Route to backfill_albums.py
        if args.check_all:
            script_args.append("--all")
        if args.limit != DEFAULT_BACKFILL_LIMIT:
            script_args.extend(["--limit", str(args.limit)])
        if args.max_tracks:
            script_args.extend(["--max-tracks", str(args.max_tracks)])
        if args.use_cache:
            script_args.append("--use-cache")
        if args.update:
            script_args.append("--update")
        if args.verbose:
            script_args.append("--verbose")
            
        exit_code = run_script("backfill_albums.py", script_args, args.verbose)
        
    elif args.command == "albums":
        # Route to check_new_albums.py (merged functionality)
        if args.url:
            script_args.extend(["--url", args.artist])
        else:
            script_args.append(args.artist)
        if args.include_variants:
            script_args.append("--include-variants")
        if args.update:
            script_args.append("--update")
        if args.verbose:
            script_args.append("--verbose")
            
        exit_code = run_script("check_new_albums.py", script_args, args.verbose)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
