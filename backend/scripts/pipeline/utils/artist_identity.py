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
        "tracks_accepted": 0,
        "tracks_blocked": 0,
        "blocked_artists": [],
    }

    if ext_df.is_empty():
        return ext_df, stats

    # Build trusted lookup: norm_artist -> (set of track_ids, set of norm_titles)
    trusted_artist_tids: dict[str, set[str]] = {}
    trusted_artist_titles: dict[str, set[str]] = {}

    for row in trusted_df.select("artist_name", "track_id", "track_name").iter_rows(named=True):
        norm_a = normalize_artist_name(row["artist_name"])
        trusted_artist_tids.setdefault(norm_a, set()).add(row["track_id"])
        if row["track_name"]:
            trusted_artist_titles.setdefault(norm_a, set()).add(
                normalize_track_name(row["track_name"])
            )

    trusted_norm_names = set(trusted_artist_tids.keys())

    # Build external per-artist info
    ext_artists: dict[str, dict] = {}
    for row in ext_df.select("artist_name", "track_id", "track_name").iter_rows(named=True):
        norm_a = normalize_artist_name(row["artist_name"])
        if norm_a not in ext_artists:
            ext_artists[norm_a] = {
                "raw_name": row["artist_name"],
                "tids": set(),
                "titles": set(),
            }
        ext_artists[norm_a]["tids"].add(row["track_id"])
        if row["track_name"]:
            ext_artists[norm_a]["titles"].add(normalize_track_name(row["track_name"]))

    # Decide which artists to accept
    accepted_norms: set[str] = set()
    blocked_norms: set[str] = set()

    for norm_a, info in ext_artists.items():
        if norm_a not in trusted_norm_names:
            # No collision — new artist, always accept
            accepted_norms.add(norm_a)
            stats["new_artists_accepted"] += 1
            continue

        # Collision detected — check for overlap evidence
        trusted_tids = trusted_artist_tids.get(norm_a, set())
        trusted_titles = trusted_artist_titles.get(norm_a, set())

        has_tid_overlap = bool(trusted_tids & info["tids"])

        title_overlap = trusted_titles & info["titles"]
        title_overlap.discard("")  # ignore empty matches
        has_title_overlap = len(title_overlap) >= min_title_overlap

        if has_tid_overlap or has_title_overlap:
            accepted_norms.add(norm_a)
            stats["colliding_accepted"] += 1
        else:
            blocked_norms.add(norm_a)
            stats["colliding_blocked"] += 1
            stats["blocked_artists"].append({
                "name": info["raw_name"],
                "ext_tracks": len(info["tids"]),
                "trusted_tracks": len(trusted_tids),
                "title_overlap": len(title_overlap),
            })

    # Filter ext_df to only accepted artists
    # Build raw name -> norm lookup, then filter by accepted norms
    all_ext_raw_names = ext_df["artist_name"].drop_nulls().unique().to_list()
    accepted_raw_names = {
        name for name in all_ext_raw_names
        if normalize_artist_name(name) in accepted_norms
    }

    accepted_df = ext_df.filter(pl.col("artist_name").is_in(list(accepted_raw_names)))

    stats["tracks_accepted"] = len(accepted_df)
    stats["tracks_blocked"] = len(ext_df) - len(accepted_df)

    if verbose:
        print(f"  Overlap merge: {stats['ext_total_artists']:,} ext artists")
        print(f"    New (no collision): {stats['new_artists_accepted']:,}")
        print(f"    Colliding accepted: {stats['colliding_accepted']:,}")
        print(f"    Colliding blocked:  {stats['colliding_blocked']:,}")
        print(f"    Tracks accepted: {stats['tracks_accepted']:,} / {stats['ext_total_tracks']:,}")

        if stats["blocked_artists"]:
            # Show top blocked by ext track count
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
