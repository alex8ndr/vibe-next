"""Gate same-name artist collisions when merging external datasets."""

from __future__ import annotations

import polars as pl

from track_dedup import normalize_artist_name, normalize_track_name


def filter_external_by_overlap(
    trusted_df: pl.DataFrame,
    ext_df: pl.DataFrame,
    *,
    min_title_overlap: int = 2,
    verbose: bool = False,
) -> tuple[pl.DataFrame, dict]:
    """Keep only external rows that pass same-artist overlap checks."""
    stats = {
        "ext_total_tracks": len(ext_df),
        "ext_total_artists": ext_df["artist_name"].n_unique(),
        "new_artists_accepted": 0,
        "colliding_accepted": 0,
        "colliding_blocked": 0,
        "colliding_superseded": 0,
        "tracks_accepted": 0,
        "tracks_blocked": 0,
        "blocked_artists": [],
        "superseded_norms": set(),
    }

    if ext_df.is_empty():
        return ext_df, stats

    # Normalize artist/track names once via vectorized map_elements
    trusted_norm = trusted_df.select(
        pl.col("artist_name").map_elements(normalize_artist_name, return_dtype=pl.Utf8).alias("_norm_artist"),
        pl.col("track_id"),
        pl.col("track_name").map_elements(
            lambda t: normalize_track_name(t) if t else "", return_dtype=pl.Utf8
        ).alias("_norm_title"),
    )
    ext_norm = ext_df.select(
        pl.col("artist_name"),
        pl.col("artist_name").map_elements(normalize_artist_name, return_dtype=pl.Utf8).alias("_norm_artist"),
        pl.col("track_id"),
        pl.col("track_name").map_elements(
            lambda t: normalize_track_name(t) if t else "", return_dtype=pl.Utf8
        ).alias("_norm_title"),
    )

    # Build trusted lookups as grouped DataFrames
    trusted_tids = (
        trusted_norm.group_by("_norm_artist")
        .agg(pl.col("track_id").alias("_trusted_tids"))
    )
    trusted_titles = (
        trusted_norm.filter(pl.col("_norm_title") != "")
        .group_by("_norm_artist")
        .agg(pl.col("_norm_title").alias("_trusted_titles"))
    )
    trusted_norm_names = set(trusted_tids["_norm_artist"].to_list())

    # Build external per-artist info as grouped DataFrame
    ext_grouped = (
        ext_norm.group_by("_norm_artist")
        .agg([
            pl.col("artist_name").first().alias("raw_name"),
            pl.col("track_id").alias("_ext_tids"),
            pl.col("_norm_title").filter(pl.col("_norm_title") != "").alias("_ext_titles"),
        ])
    )

    # Decide which normalized artist names to accept
    accepted_norms: set[str] = set()
    blocked_norms: set[str] = set()

    # Pre-build trusted lookup dicts from grouped frames (much smaller than row-level)
    trusted_tid_map: dict[str, set[str]] = {}
    for row in trusted_tids.iter_rows(named=True):
        trusted_tid_map[row["_norm_artist"]] = set(row["_trusted_tids"])

    trusted_title_map: dict[str, set[str]] = {}
    for row in trusted_titles.iter_rows(named=True):
        trusted_title_map[row["_norm_artist"]] = set(row["_trusted_titles"])

    for row in ext_grouped.iter_rows(named=True):
        norm_a = row["_norm_artist"]

        if norm_a not in trusted_norm_names:
            accepted_norms.add(norm_a)
            stats["new_artists_accepted"] += 1
            continue

        # Collision detected — check overlap
        t_tids = trusted_tid_map.get(norm_a, set())
        t_titles = trusted_title_map.get(norm_a, set())
        e_tids = set(row["_ext_tids"])
        e_titles = set(row["_ext_titles"])

        has_tid_overlap = bool(t_tids & e_tids)
        title_overlap = t_titles & e_titles
        title_overlap.discard("")
        has_title_overlap = len(title_overlap) >= min_title_overlap

        if has_tid_overlap or has_title_overlap:
            accepted_norms.add(norm_a)
            stats["colliding_accepted"] += 1
        elif len(e_tids) > len(t_tids):
            # Different person, but external has bigger catalog — likely the
            # more notable artist.  Accept external & supersede trusted.
            accepted_norms.add(norm_a)
            stats["superseded_norms"].add(norm_a)
            stats["colliding_superseded"] += 1
            if verbose:
                print(f"    Superseded: {row['raw_name']} (ext={len(e_tids)} > trusted={len(t_tids)})")
        else:
            blocked_norms.add(norm_a)
            stats["colliding_blocked"] += 1
            stats["blocked_artists"].append({
                "name": row["raw_name"],
                "ext_tracks": len(e_tids),
                "trusted_tracks": len(t_tids),
                "title_overlap": len(title_overlap),
            })

    # Filter ext_df using the normalized artist column
    ext_with_norm = ext_df.with_columns(
        pl.col("artist_name").map_elements(normalize_artist_name, return_dtype=pl.Utf8).alias("_norm_artist")
    )
    accepted_df = ext_with_norm.filter(
        pl.col("_norm_artist").is_in(list(accepted_norms))
    ).drop("_norm_artist")

    stats["tracks_accepted"] = len(accepted_df)
    stats["tracks_blocked"] = len(ext_df) - len(accepted_df)

    if verbose:
        print(f"  Overlap merge: {stats['ext_total_artists']:,} ext artists")
        print(f"    New (no collision):   {stats['new_artists_accepted']:,}")
        print(f"    Colliding accepted:   {stats['colliding_accepted']:,}")
        print(f"    Colliding superseded: {stats['colliding_superseded']:,}")
        print(f"    Colliding blocked:    {stats['colliding_blocked']:,}")
        print(f"    Tracks accepted: {stats['tracks_accepted']:,} / {stats['ext_total_tracks']:,}")

        if stats["blocked_artists"]:
            top_blocked = sorted(
                stats["blocked_artists"],
                key=lambda x: x["ext_tracks"],
                reverse=True,
            )[:10]
            print(f"    Top blocked artists:")
            for b in top_blocked:
                print(
                    f"      - {b['name']}: ext={b['ext_tracks']}, "
                    f"trusted={b['trusted_tracks']}, titles={b['title_overlap']}"
                )

    return accepted_df, stats
