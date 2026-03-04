#!/usr/bin/env python3
"""Ensure data_encoded.parquet is available before starting the app.

Downloads from Backblaze B2 if the file is missing or stale.

Called from entrypoint.sh before uvicorn starts.

Staleness is detected by comparing B2's upload timestamp against the
local file's mtime.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import ENCODED_DATASET


def _b2_configured() -> bool:
    return all(
        os.environ.get(v, "").strip()
        for v in ("VIBE_B2_KEY_ID", "VIBE_B2_APP_KEY", "VIBE_B2_BUCKET")
    )


def _is_stale() -> bool:
    """Check if the remote file is newer than the local one."""
    from b2_oneway_sync import get_remote_timestamp

    remote_ts_ms = get_remote_timestamp(ENCODED_DATASET)
    if remote_ts_ms is None:
        print("[ensure_data] Remote file not found in B2, skipping update")
        return False

    local_mtime = ENCODED_DATASET.stat().st_mtime
    remote_ts = remote_ts_ms / 1000  # ms -> seconds

    if remote_ts > local_mtime:
        local_dt = datetime.fromtimestamp(local_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        remote_dt = datetime.fromtimestamp(remote_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"[ensure_data] Newer data available (local: {local_dt}, remote: {remote_dt})")
        return True

    print("[ensure_data] Data is up to date")
    return False


def _download_data() -> None:
    """Download data_encoded.parquet from B2."""
    from b2_oneway_sync import download

    print("[ensure_data] Downloading data_encoded.parquet from B2...")
    download(ENCODED_DATASET)
    size_mb = ENCODED_DATASET.stat().st_size / 1024 / 1024
    print(f"[ensure_data] Downloaded ({size_mb:.1f} MB)")


def main() -> int:
    if not _b2_configured():
        if ENCODED_DATASET.exists():
            print("[ensure_data] B2 not configured, using existing local data")
            return 0
        print("[ensure_data] ERROR: No data and B2 not configured")
        print("[ensure_data] Set VIBE_B2_KEY_ID, VIBE_B2_APP_KEY, VIBE_B2_BUCKET")
        return 1

    if ENCODED_DATASET.exists():
        try:
            if not _is_stale():
                size_mb = ENCODED_DATASET.stat().st_size / 1024 / 1024
                print(f"[ensure_data] Using existing data ({size_mb:.1f} MB)")
                return 0
        except Exception as e:
            print(f"[ensure_data] Staleness check failed ({e}), using existing data")
            return 0

    try:
        _download_data()
        return 0
    except Exception as e:
        if ENCODED_DATASET.exists():
            print(f"[ensure_data] Download failed ({e}), using existing data")
            return 0
        print(f"[ensure_data] ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
