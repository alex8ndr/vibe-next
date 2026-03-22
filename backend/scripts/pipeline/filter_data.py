#!/usr/bin/env python3
"""
Filter raw Spotify data to remove unwanted content before processing.

Uses Polars for memory-efficient processing on VPS (800MB RAM limit).
Supports both Parquet (preferred) and legacy CSV input.

Usage:
    # Default: use paths from paths.py
    python filter_data.py
    
    # Custom input/output
    python filter_data.py -i data.parquet -o data_filtered.parquet
    
    # Legacy CSV support (auto-detected)
    python filter_data.py -i data.csv.zip -o data_filtered.parquet
"""

import argparse
import sys
from pathlib import Path

import polars as pl

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from paths import (
    FILTERED_DATASET,
)
from io_utils import (
    read_input_file, 
    atomic_write_parquet,
    validate_filtered_dataset,
)
from artist_reassignments import get_reassigned_artists, get_artist_genre
from schema import normalize_for_merge
from genre_families import GENRE_DEFINITIONS
from genre_mapping import build_artist_genre_map, apply_artist_genre_map, enrich_genres, map_raw_genre
from pipeline.utils.artist_identity import filter_external_by_overlap
from pipeline.utils.dataset_resolver import resolve_filter_inputs, add_dataset_selection_args

# Artists to exclude entirely (not reassign)
EXCLUDED_ARTISTS: set[str] = set()

# Genres to exclude entirely
EXCLUDED_GENRES = {
    'comedy',   # Spoken word, not music
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter raw Spotify data before processing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=None,
        help="Path to input file (parquet or csv.zip). Default: auto-detect from paths.py",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Path to output parquet file. Default: data_filtered.parquet",
    )
    parser.add_argument(
        "--keep-remixes",
        action="store_true",
        default=False,
        help="Keep remix tracks (by default they are removed)",
    )
    parser.add_argument(
        "--keep-live",
        action="store_true",
        default=False,
        help="Keep live versions (by default obvious live recordings are removed)",
    )
    parser.add_argument(
        "--min-songs",
        type=int,
        default=2,
        help="Minimum songs an artist must have to be included",
    )
    parser.add_argument(
        "--merge",
        type=Path,
        nargs="*",
        default=None,
        help="Additional parquet files to merge before filtering (e.g., external datasets)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip genre enrichment from external artist data",
    )
    parser.add_argument(
        "--preserve-genres",
        action="store_true",
        default=False,
        help="Keep original genres instead of overriding with external data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be filtered without writing output",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed filtering info",
    )
    add_dataset_selection_args(parser)
    return parser.parse_args()


def filter_data(
    input_path: Path,
    output_path: Path | None = None,
    keep_remixes: bool = False,
    keep_live: bool = False,
    min_songs: int = 1,
    dry_run: bool = False,
    verbose: bool = False,
    merge_paths: list[Path] | None = None,
    enrich: bool = True,
    preserve_genres: bool = False,
    added_artists_path: Path | None = None,
) -> tuple[dict, pl.DataFrame]:
    """
    Filter dataset using Polars for memory efficiency.
    
    Returns (stats, filtered_df) tuple.
    If output_path is None, skips writing to disk.
    """
    
    # Identify added_artists so they can be protected from override-only filtering
    added_artist_names: set[str] = set()
    if added_artists_path and added_artists_path.exists():
        df_added_tmp = read_input_file(added_artists_path, normalize_schema=True)
        if "artist_name" in df_added_tmp.columns:
            added_artist_names = set(df_added_tmp["artist_name"].drop_nulls().unique().to_list())
        del df_added_tmp

    print(f"Loading {input_path}...")
    df = read_input_file(input_path)
    
    if verbose:
        mem_mb = df.estimated_size() / (1024 * 1024)
        print(f"  Loaded {len(df):,} rows ({mem_mb:.1f} MB in memory)")
    
    # Merge additional datasets before filtering
    if merge_paths:
        df_primary = normalize_for_merge(df)
        n_primary = len(df_primary)

        # Build trusted base: primary + added_artists (hand-curated, always trusted)
        trusted_parts = [df_primary]
        if added_artists_path and added_artists_path.exists():
            df_added = read_input_file(added_artists_path, normalize_schema=True)
            df_added = normalize_for_merge(df_added)
            trusted_parts.append(df_added)
            if verbose:
                print(f"  Trusted added_artists: {len(df_added):,} rows")

        trusted_df = pl.concat(trusted_parts, how="diagonal") if len(trusted_parts) > 1 else df_primary
        trusted_df = trusted_df.unique(subset=["track_id"], keep="first")

        dfs_to_merge = [trusted_df]
        source_counts = {"trusted": len(trusted_df)}
        all_superseded_norms: set[str] = set()

        # Merge external datasets with overlap-based safety gate
        for mp in merge_paths:
            if added_artists_path and mp.resolve() == added_artists_path.resolve():
                continue  # already included in trusted base
            if mp.exists():
                print(f"Merging {mp.name} (overlap-gated)...")
                df_ext = read_input_file(mp, normalize_schema=True)
                df_ext = normalize_for_merge(df_ext)
                source_counts[mp.name] = len(df_ext)
                df_ext, overlap_stats = filter_external_by_overlap(
                    trusted_df, df_ext, verbose=verbose,
                )
                dfs_to_merge.append(df_ext)
                all_superseded_norms |= overlap_stats.get("superseded_norms", set())
            else:
                print(f"Warning: merge file not found: {mp}")

        # Remove superseded artists from trusted before concat so we don't
        # mix two different people's tracks under the same name.
        if all_superseded_norms:
            from track_dedup import normalize_artist_name
            dfs_to_merge[0] = dfs_to_merge[0].filter(
                ~pl.col("artist_name").map_elements(
                    normalize_artist_name, return_dtype=pl.Utf8
                ).is_in(list(all_superseded_norms))
            )
            n_removed = len(trusted_df) - len(dfs_to_merge[0])
            if verbose:
                print(f"  Removed {n_removed:,} trusted tracks for {len(all_superseded_norms):,} superseded artists")

        if len(dfs_to_merge) > 1:
            n_total_pre_dedup = sum(len(d) for d in dfs_to_merge)
            df = pl.concat(dfs_to_merge, how="diagonal")
            # Deduplicate on track_id, keeping trusted dataset entries (first)
            df = df.unique(subset=["track_id"], keep="first")
            n_trackid_dedup = n_total_pre_dedup - len(df)
            print(f"After merge + track_id dedup: {len(df):,} tracks ({n_trackid_dedup:,} exact track_id duplicates removed)")
            if verbose:
                for src, cnt in source_counts.items():
                    print(f"  Source {src}: {cnt:,} input tracks")
        else:
            df = trusted_df
    
    original_count = len(df)
    original_artists = df['artist_name'].n_unique() if 'artist_name' in df.columns else 0
    
    stats = {
        'original_tracks': original_count,
        'original_artists': original_artists,
        'removed': {},
    }
    
    # Filter 0: Remove rows with null required fields (data quality - first!)
    required_fields = ["artist_name", "track_name", "track_id"]
    null_removed = 0
    for field in required_fields:
        if field in df.columns:
            null_count = df[field].null_count()
            if null_count > 0:
                df = df.filter(pl.col(field).is_not_null())
                null_removed += null_count
                if verbose:
                    print(f"  Null {field}: {null_count:,} rows removed")
    stats['removed']['null_required_fields'] = null_removed
    
    # Get reassigned artists for genre updates
    reassigned = get_reassigned_artists()
    effective_exclusions = EXCLUDED_ARTISTS - reassigned
    
    # Build filter expressions using Polars
    filters = []
    
    # Filter 1: Excluded artists (but not those with reassignments)
    if 'artist_name' in df.columns and effective_exclusions:
        excluded_mask = df['artist_name'].is_in(list(effective_exclusions)).fill_null(False)
        stats['removed']['excluded_artists'] = excluded_mask.sum()
        if verbose and stats['removed']['excluded_artists'] > 0:
            print(f"  Excluded artists: {stats['removed']['excluded_artists']:,} tracks")
        filters.append(~excluded_mask)
    else:
        stats['removed']['excluded_artists'] = 0
    
    # Filter 2: Excluded genres
    if 'genre' in df.columns:
        # Treat null genres as not excluded (avoid dropping nulls before enrichment)
        genre_mask = df['genre'].is_in(list(EXCLUDED_GENRES)).fill_null(False)
        stats['removed']['excluded_genres'] = genre_mask.sum()
        if verbose and stats['removed']['excluded_genres'] > 0:
            for g in EXCLUDED_GENRES:
                count = (df['genre'] == g).sum()
                if count > 0:
                    print(f"  Genre '{g}': {count:,} tracks")
        filters.append(~genre_mask)
    else:
        stats['removed']['excluded_genres'] = 0
    
    # Filter 3: Content-type filters on track_name (remix, performances, live)
    # Pre-compute lowercased track_name once for all regex checks
    stats['removed']['remixes'] = 0
    stats['removed']['performances'] = 0
    stats['removed']['live_versions'] = 0
    if 'track_name' in df.columns:
        track_lower = df['track_name'].cast(pl.Utf8).str.to_lowercase().fill_null("")

        if not keep_remixes:
            remix_mask = track_lower.str.contains(r'\bremix\b').fill_null(False)
            stats['removed']['remixes'] = remix_mask.sum()
            if verbose:
                print(f"  Remixes: {stats['removed']['remixes']:,} tracks")
            filters.append(~remix_mask)

        perf_mask = track_lower.str.contains(
            r'\s+[-–—]\s+the\s+voice(\s+performance)?\s*$'
        ).fill_null(False)
        stats['removed']['performances'] = perf_mask.sum()
        if verbose:
            print(f"  Performances: {stats['removed']['performances']:,} tracks")
        filters.append(~perf_mask)

        if not keep_live:
            live_mask = track_lower.str.contains(
                r'(?:\s[-–—]\s*live(?:\s+at|\s+from|\s+in|\s*$)|\((?:[^)]*\blive\b[^)]*)\)|\[(?:[^\]]*\blive\b[^\]]*)\])'
            ).fill_null(False)
            stats['removed']['live_versions'] = live_mask.sum()
            if verbose:
                print(f"  Live versions: {stats['removed']['live_versions']:,} tracks")
            filters.append(~live_mask)
    
    # Apply all content filters at once
    if filters:
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f
        df = df.filter(combined_filter)
    
    # Apply genre reassignments AFTER content filtering
    if reassigned and 'genre' in df.columns and 'artist_name' in df.columns:
        reassign_mask = df['artist_name'].is_in(list(reassigned))
        n_reassigned = reassign_mask.sum()
        
        if n_reassigned > 0:
            # Get the new genres for reassigned artists
            # We need to do this row by row since get_artist_genre is a lookup
            artist_to_genre = {a: get_artist_genre(a) for a in reassigned}
            
            # Use when/then/otherwise for conditional update
            df = df.with_columns(
                pl.when(pl.col('artist_name').is_in(list(reassigned)))
                .then(pl.col('artist_name').replace(artist_to_genre))
                .otherwise(pl.col('genre'))
                .alias('genre')
            )
            
            if verbose:
                print(f"  Reassigned genres for {n_reassigned:,} tracks")
    
    # Genre enrichment from external artist data
    if enrich and 'genre' in df.columns:
        n_before_enrich = len(df)
        null_before_enrich = df['genre'].null_count()
        if not preserve_genres:
            # Default: override-only mode — replace genres with external matches
            locked = reassigned | added_artist_names
            name_to_genre = build_artist_genre_map(
                df,
                override=True,
                locked_artists=locked,
            )
            if name_to_genre:
                n_matched = len(name_to_genre)
                df = apply_artist_genre_map(
                    df,
                    name_to_genre,
                    override=True,
                    keep_ext_genre=True,
                )
                keep_mask = pl.col("_ext_genre").is_not_null()
                if added_artist_names:
                    keep_mask = keep_mask | pl.col("artist_name").is_in(list(added_artist_names))
                if reassigned:
                    keep_mask = keep_mask | pl.col("artist_name").is_in(list(reassigned))
                df = df.filter(keep_mask).drop("_ext_genre")
            else:
                n_matched = 0
                keep_names = added_artist_names | reassigned
                if keep_names:
                    df = df.filter(pl.col("artist_name").is_in(list(keep_names)))
                else:
                    df = df.filter(pl.lit(False))
            stats['removed']['override_only'] = n_before_enrich - len(df)
            stats['genres_enriched'] = n_matched
        else:
            df = enrich_genres(
                df,
                verbose=verbose,
                override=False,
                locked_artists=reassigned,
            )
            null_after_enrich = df['genre'].null_count()
            stats['genres_enriched'] = null_before_enrich - null_after_enrich
    else:
        stats['genres_enriched'] = 0

    # Normalize existing raw genre strings into internal vocabulary where possible.
    if 'genre' in df.columns:
        raw_genres = df['genre'].drop_nulls().unique().to_list()
        canon_pairs = []
        for g in raw_genres:
            mapped = map_raw_genre(g)
            if mapped and mapped != g:
                canon_pairs.append((g, mapped))
        if canon_pairs:
            canon_df = pl.DataFrame(
                {"_raw_genre": [p[0] for p in canon_pairs], "_canon_genre": [p[1] for p in canon_pairs]},
            )
            df = df.join(canon_df, left_on="genre", right_on="_raw_genre", how="left")
            df = df.with_columns(
                pl.when(pl.col("_canon_genre").is_not_null())
                .then(pl.col("_canon_genre"))
                .otherwise(pl.col("genre"))
                .alias("genre")
            ).drop("_canon_genre")
            if verbose:
                print(f"  Canonicalized existing genre labels: {len(canon_pairs):,} distinct mappings applied")

    # Filter 4: Drop unmapped genres when override mode is enabled
    if not preserve_genres and 'genre' in df.columns:
        valid_genres = list(GENRE_DEFINITIONS.keys())
        unmapped_mask = pl.col("genre").is_null() | ~pl.col("genre").is_in(valid_genres)
        unmapped_count = df.filter(unmapped_mask).height
        stats['removed']['unmapped_genres'] = unmapped_count
        if verbose and unmapped_count > 0:
            print(f"  Unmapped genres (override mode): {unmapped_count:,} tracks")
        df = df.filter(~unmapped_mask)
    else:
        stats['removed']['unmapped_genres'] = 0

    # Filter 5: Minimum songs per artist
    if min_songs > 1 and 'artist_name' in df.columns:
        before_min = len(df)
        
        # Count tracks per artist
        artist_counts = df.group_by('artist_name').agg(pl.len().alias('_count'))
        keep_artists = artist_counts.filter(pl.col('_count') >= min_songs).select('artist_name')

        df = df.join(keep_artists, on='artist_name', how='semi')
        stats['removed']['min_songs'] = before_min - len(df)
        
        if verbose:
            removed_artists = len(artist_counts) - len(keep_artists)
            print(f"  Artists with < {min_songs} songs: {removed_artists:,} artists removed")
    else:
        stats['removed']['min_songs'] = 0
    
    stats['final_tracks'] = len(df)
    stats['final_artists'] = df['artist_name'].n_unique() if 'artist_name' in df.columns else 0
    stats['total_removed'] = original_count - len(df)
    
    if not dry_run and output_path is not None:
        print(f"Saving to {output_path}...")
        atomic_write_parquet(
            df, 
            output_path, 
            validate=validate_filtered_dataset,
            verbose=verbose,
        )
    
    return stats, df


def main() -> None:
    args = parse_args()
    
    # Resolve datasets via shared resolver
    try:
        resolution = resolve_filter_inputs(
            input_path=args.input,
            merge_paths=list(args.merge) if args.merge else None,
            datasets=args.datasets,
            all_datasets=args.all_datasets,
            exclude_datasets=args.exclude_datasets,
            primary_dataset=args.primary_dataset,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    input_path = resolution.input_path
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Primary dataset: {resolution.primary_name} ({input_path.name})")
    if resolution.merge_paths:
        merge_names = [p.stem for p in resolution.merge_paths]
        print(f"Merge datasets: {', '.join(merge_names)}")

    # Resolve output path
    output_path = args.output or FILTERED_DATASET
    
    merge_paths = resolution.merge_paths or None
    
    stats, _df = filter_data(
        input_path=input_path,
        output_path=output_path,
        keep_remixes=args.keep_remixes,
        keep_live=args.keep_live,
        min_songs=args.min_songs,
        dry_run=args.dry_run,
        verbose=args.verbose,
        merge_paths=merge_paths,
        enrich=not args.no_enrich,
        preserve_genres=args.preserve_genres,
        added_artists_path=resolution.added_artists_path,
    )
    
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Filtering Summary:")
    print(f"  Original: {stats['original_tracks']:,} tracks, {stats['original_artists']:,} artists")
    if merge_paths:
        print(f"  Merged:   {len(merge_paths)} additional file(s)")
    print(f"  Removed:")
    print(f"    - Null fields:      {stats['removed']['null_required_fields']:,}")
    print(f"    - Excluded artists: {stats['removed']['excluded_artists']:,}")
    print(f"    - Excluded genres:  {stats['removed']['excluded_genres']:,}")
    print(f"    - Remixes:          {stats['removed']['remixes']:,}")
    print(f"    - Live versions:    {stats['removed']['live_versions']:,}")
    print(f"    - Performances:     {stats['removed']['performances']:,}")
    print(f"    - Unmapped genres:  {stats['removed']['unmapped_genres']:,}")
    print(f"    - Min songs filter: {stats['removed']['min_songs']:,}")
    if 'override_only' in stats['removed']:
        print(f"    - Override-only:    {stats['removed']['override_only']:,}")
    print(f"    - Total:            {stats['total_removed']:,}")
    print(f"  Genre enrichment:     {stats['genres_enriched']:,} tracks enriched")
    print(f"  Final: {stats['final_tracks']:,} tracks, {stats['final_artists']:,} artists")
    
    if not args.dry_run:
        print(f"\nOutput: {output_path}")
        print(f"Next: python process_data.py -i {output_path}")


if __name__ == "__main__":
    main()
