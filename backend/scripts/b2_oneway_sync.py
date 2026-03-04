#!/usr/bin/env python3
"""Minimal one-way Backblaze B2 sync for Vibe datasets.

Modes:
- upload: local file -> timestamped key (+ optional latest key)
- download: remote key -> local file (atomic temp rename)
- list: show available remote keys under prefix

Required env vars:
- VIBE_B2_KEY_ID
- VIBE_B2_APP_KEY
- VIBE_B2_BUCKET
Optional env vars:
- VIBE_B2_PREFIX (default: vibe-data)
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path


def _require_b2sdk():
    try:
        from b2sdk.v2 import B2Api, InMemoryAccountInfo
    except Exception as exc:
        raise SystemExit("b2sdk missing. Install with: pip install b2sdk") from exc
    return B2Api, InMemoryAccountInfo


def _load_config() -> tuple[str, str, str, str]:
    key_id = os.environ.get("VIBE_B2_KEY_ID", "").strip()
    app_key = os.environ.get("VIBE_B2_APP_KEY", "").strip()
    bucket = os.environ.get("VIBE_B2_BUCKET", "").strip()
    prefix = os.environ.get("VIBE_B2_PREFIX", "vibe-data").strip().strip("/")

    if not key_id or not app_key or not bucket:
        raise SystemExit(
            "Missing B2 env vars. Required: VIBE_B2_KEY_ID, VIBE_B2_APP_KEY, VIBE_B2_BUCKET"
        )

    return key_id, app_key, bucket, prefix


def _get_bucket():
    B2Api, InMemoryAccountInfo = _require_b2sdk()
    key_id, app_key, bucket_name, prefix = _load_config()

    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", key_id, app_key)
    bucket = api.get_bucket_by_name(bucket_name)
    return bucket, prefix


def _timestamp_key(prefix: str, basename: str, ext: str = ".parquet") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}/datasets/{basename}-{ts}{ext}"


def _latest_key(prefix: str, basename: str, ext: str = ".parquet") -> str:
    return f"{prefix}/datasets/{basename}-latest{ext}"


def get_remote_timestamp(target_file: Path) -> int | None:
    """Get B2 upload timestamp (ms since epoch) for the latest version of a file.

    Returns None if the file doesn't exist remotely.  Uses only the list API
    (no download, negligible bandwidth).
    """
    bucket, prefix = _get_bucket()
    remote_key = _latest_key(prefix, target_file.stem, target_file.suffix)

    for file_version, _folder in bucket.ls(
        folder_to_list=f"{prefix}/datasets/",
        latest_only=True,
    ):
        if file_version.file_name == remote_key:
            return file_version.upload_timestamp
    return None


def upload(local_file: Path, *, write_latest: bool) -> None:
    if not local_file.exists():
        raise SystemExit(f"Local file not found: {local_file}")

    bucket, prefix = _get_bucket()
    base = local_file.stem
    ext = local_file.suffix

    key_ts = _timestamp_key(prefix, base, ext)
    print(f"Uploading timestamped object: {key_ts}")
    bucket.upload_local_file(local_file=str(local_file), file_name=key_ts)

    if write_latest:
        key_latest = _latest_key(prefix, base, ext)
        print(f"Uploading latest object: {key_latest}")
        bucket.upload_local_file(local_file=str(local_file), file_name=key_latest)

    print("Upload complete.")


def download(output_file: Path, remote_key: str | None = None) -> None:
    bucket, prefix = _get_bucket()

    if remote_key is None:
        remote_key = _latest_key(prefix, output_file.stem, output_file.suffix)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_file.with_suffix(output_file.suffix + ".tmp")

    if temp_path.exists():
        temp_path.unlink()

    print(f"Downloading: {remote_key}")
    bucket.download_file_by_name(remote_key).save_to(str(temp_path))
    os.replace(temp_path, output_file)
    print(f"Download complete: {output_file}")


def list_keys(limit: int) -> None:
    bucket, prefix = _get_bucket()
    query_prefix = f"{prefix}/datasets/"
    print(f"Listing keys under: {query_prefix}")

    count = 0
    for file_version, _folder in bucket.ls(folder_to_list=query_prefix, latest_only=True):
        print(f"- {file_version.file_name}  ({file_version.size:,} bytes)")
        count += 1
        if count >= limit:
            break

    if count == 0:
        print("No objects found.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal one-way B2 sync")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="Upload local parquet to B2")
    up.add_argument("--file", type=Path, required=True, help="Local parquet file to upload")
    up.add_argument(
        "--no-latest",
        action="store_true",
        help="Skip uploading *-latest.parquet object",
    )

    down = sub.add_parser("download", help="Download parquet from B2")
    down.add_argument("--output", type=Path, required=True, help="Local output parquet path")
    down.add_argument(
        "--remote-key",
        default=None,
        help="Explicit remote key. Default uses <prefix>/datasets/<output-stem>-latest.parquet",
    )

    ls = sub.add_parser("list", help="List remote dataset keys")
    ls.add_argument("--limit", type=int, default=20)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "upload":
        upload(args.file, write_latest=not args.no_latest)
        return
    if args.command == "download":
        download(args.output, args.remote_key)
        return
    if args.command == "list":
        list_keys(args.limit)
        return


if __name__ == "__main__":
    main()
