#!/usr/bin/env python3
"""Ensure split serving datasets are available before starting the app.

Downloads from Backblaze B2 if files are missing or stale.

Called from entrypoint.sh before uvicorn starts.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import TRACKS_DATASET, ARTISTS_DATASET

SERVING_FILES = (TRACKS_DATASET, ARTISTS_DATASET)


def _b2_configured() -> bool:
    return all(
        os.environ.get(v, "").strip()
        for v in ("VIBE_B2_KEY_ID", "VIBE_B2_APP_KEY", "VIBE_B2_BUCKET")
    )


def _skip_b2_sync() -> bool:
    value = os.environ.get("VIBE_SKIP_B2_SYNC", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _all_files_present() -> bool:
    return all(path.exists() for path in SERVING_FILES)


def _format_missing_files() -> str:
    missing = [p.name for p in SERVING_FILES if not p.exists()]
    return ", ".join(missing)


def _local_total_mb() -> float:
    return sum(p.stat().st_size for p in SERVING_FILES if p.exists()) / 1024 / 1024


def _is_stale() -> bool:
    """Check if any remote serving file is newer than the local one."""
    from b2_oneway_sync import get_remote_timestamp

    stale = False
    any_remote_seen = False

    for dataset_path in SERVING_FILES:
        remote_ts_ms = get_remote_timestamp(dataset_path)
        if remote_ts_ms is None:
            print(f"[ensure_data] Remote file not found in B2: {dataset_path.name}")
            continue

        any_remote_seen = True
        remote_ts = remote_ts_ms / 1000
        if not dataset_path.exists():
            print(f"[ensure_data] Missing local file: {dataset_path.name}, remote exists")
            stale = True
            continue

        local_mtime = dataset_path.stat().st_mtime
        if remote_ts > local_mtime:
            local_dt = datetime.fromtimestamp(local_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            remote_dt = datetime.fromtimestamp(remote_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(
                f"[ensure_data] Newer remote file for {dataset_path.name} "
                f"(local: {local_dt}, remote: {remote_dt})"
            )
            stale = True

    if not any_remote_seen:
        print("[ensure_data] No remote serving files found in B2, skipping update")
        return False

    if not stale:
        print("[ensure_data] Serving data is up to date")

    return stale


def _download_data() -> None:
    """Download split serving files from B2."""
    from b2_oneway_sync import download

    for dataset_path in SERVING_FILES:
        print(f"[ensure_data] Downloading {dataset_path.name} from B2...")
        download(dataset_path)

    if not _all_files_present():
        raise RuntimeError(f"Missing files after download: {_format_missing_files()}")

    size_mb = _local_total_mb()
    print(f"[ensure_data] Downloaded serving data ({size_mb:.1f} MB total)")


def main() -> int:
    if _skip_b2_sync():
        if _all_files_present():
            size_mb = _local_total_mb()
            print(f"[ensure_data] B2 sync skipped by VIBE_SKIP_B2_SYNC, using local split data ({size_mb:.1f} MB total)")
            return 0
        print("[ensure_data] ERROR: VIBE_SKIP_B2_SYNC is enabled but local split data is missing")
        print(f"[ensure_data] Missing: {_format_missing_files()}")
        return 1

    if not _b2_configured():
        if _all_files_present():
            print("[ensure_data] B2 not configured, using existing local split data")
            return 0
        print("[ensure_data] ERROR: Missing local split data and B2 not configured")
        print(f"[ensure_data] Missing: {_format_missing_files()}")
        print("[ensure_data] Set VIBE_B2_KEY_ID, VIBE_B2_APP_KEY, VIBE_B2_BUCKET")
        return 1

    if _all_files_present():
        try:
            if not _is_stale():
                size_mb = _local_total_mb()
                print(f"[ensure_data] Using existing split data ({size_mb:.1f} MB total)")
                return 0
        except Exception as e:
            print(f"[ensure_data] Staleness check failed ({e}), using existing local split data")
            return 0

    try:
        _download_data()
        return 0
    except Exception as e:
        if _all_files_present():
            print(f"[ensure_data] Download failed ({e}), using existing local split data")
            return 0
        print(f"[ensure_data] ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
