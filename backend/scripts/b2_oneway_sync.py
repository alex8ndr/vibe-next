#!/usr/bin/env python3
"""Minimal one-way Backblaze B2 sync for Vibe datasets.

Modes:
- upload: local file -> timestamped key (+ optional latest key)
- download: remote key -> local file (atomic temp rename)
- list: show available remote keys under prefix
- backup: archive gitignored-but-important dirs to B2
- restore: download and extract a backup archive from B2

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
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_BACKUP_PATHS = [
    "backend/dev/",
    "backend/scripts/devtools/",
    "backend/scripts/ingest/",
    "backend/data/external/genre/",
]

# Also back up any .parquet files directly in external/ (processed track datasets).
_BACKUP_EXTERNAL_GLOBS = [
    "backend/data/external/*.parquet",
]

_BACKUP_ARCHIVE_NAME = "vibe-local-backup"


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


def _backup_key_latest(prefix: str) -> str:
    return f"{prefix}/backups/{_BACKUP_ARCHIVE_NAME}-latest.tar"


def _backup_key_timestamped(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}/backups/{_BACKUP_ARCHIVE_NAME}-{ts}.tar"


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


def upload(local_file: Path, *, write_latest: bool = True, write_archive: bool = False) -> None:
    if not local_file.exists():
        raise SystemExit(f"Local file not found: {local_file}")

    bucket, prefix = _get_bucket()
    base = local_file.stem
    ext = local_file.suffix

    if write_archive:
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


def backup(*, write_archive: bool = False, dry_run: bool = False) -> None:
    repo_root = _REPO_ROOT

    resolved_paths: list[tuple[str, Path]] = []
    for rel in _BACKUP_PATHS:
        full = repo_root / rel
        if not full.exists():
            print(f"WARNING: skipping (not found): {rel}")
            continue
        resolved_paths.append((rel, full))

    for pattern in _BACKUP_EXTERNAL_GLOBS:
        for full in sorted(repo_root.glob(pattern)):
            rel = str(full.relative_to(repo_root)).replace("\\", "/")
            resolved_paths.append((rel, full))

    if not resolved_paths:
        raise SystemExit("No backup paths found – nothing to archive.")

    total_bytes = 0
    print("Backup contents:")
    for rel, full in resolved_paths:
        if full.is_dir():
            size = sum(f.stat().st_size for f in full.rglob("*") if f.is_file())
        else:
            size = full.stat().st_size
        total_bytes += size
        print(f"  + {rel}  ({size / 1024 / 1024:.1f} MB)")
    print(f"  Total (uncompressed): {total_bytes / 1024 / 1024:.1f} MB")

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with tarfile.open(tmp_path, "w") as tar:
            for rel, full in resolved_paths:
                tar.add(str(full), arcname=rel)

        archive_mb = tmp_path.stat().st_size / 1024 / 1024
        print(f"  Archive size: {archive_mb:.1f} MB")

        if dry_run:
            print("Dry run – nothing uploaded.")
            return

        bucket, prefix = _get_bucket()

        key_latest = _backup_key_latest(prefix)
        print(f"Uploading latest backup: {key_latest}")
        bucket.upload_local_file(local_file=str(tmp_path), file_name=key_latest)

        if write_archive:
            key_ts = _backup_key_timestamped(prefix)
            print(f"Uploading timestamped backup: {key_ts}")
            bucket.upload_local_file(local_file=str(tmp_path), file_name=key_ts)

        print("Backup complete.")
    finally:
        tmp_path.unlink(missing_ok=True)


def restore(*, overwrite: bool = False, output_dir: Path | None = None) -> None:
    extract_root = output_dir if output_dir is not None else _REPO_ROOT

    bucket, prefix = _get_bucket()
    key_latest = _backup_key_latest(prefix)

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        print(f"Downloading: {key_latest}")
        bucket.download_file_by_name(key_latest).save_to(str(tmp_path))

        with tarfile.open(tmp_path, "r:") as tar:
            # Path traversal safety check
            for member in tar.getmembers():
                resolved = (extract_root / member.name).resolve()
                if not str(resolved).startswith(str(extract_root.resolve())):
                    raise SystemExit(
                        f"Refusing to extract – path traversal detected: {member.name}"
                    )

            if not overwrite:
                existing = []
                for member in tar.getmembers():
                    target = extract_root / member.name
                    if target.exists():
                        existing.append(member.name)
                if existing:
                    print("The following paths already exist:")
                    for p in existing[:10]:
                        print(f"  - {p}")
                    if len(existing) > 10:
                        print(f"  ... and {len(existing) - 10} more")
                    raise SystemExit(
                        "Refusing to extract without --overwrite."
                    )

            print(f"Extracting to: {extract_root}")
            tar.extractall(path=str(extract_root))

        print("Restore complete.")
    finally:
        tmp_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal one-way B2 sync")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="Upload local parquet to B2")
    up.add_argument("--file", type=Path, required=True, help="Local parquet file to upload")
    up.add_argument(
        "--archive",
        action="store_true",
        help="Also upload a timestamped archive copy",
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

    bk = sub.add_parser("backup", help="Archive gitignored dirs to B2")
    bk.add_argument(
        "--archive",
        action="store_true",
        help="Also upload a timestamped archive copy",
    )
    bk.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be backed up (with sizes) without uploading",
    )

    rs = sub.add_parser("restore", help="Restore backup archive from B2")
    rs.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing paths during extraction",
    )
    rs.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to extract into (default: repo root)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "upload":
        upload(args.file, write_archive=args.archive)
        return
    if args.command == "download":
        download(args.output, args.remote_key)
        return
    if args.command == "list":
        list_keys(args.limit)
        return
    if args.command == "backup":
        backup(write_archive=args.archive, dry_run=args.dry_run)
        return
    if args.command == "restore":
        restore(overwrite=args.overwrite, output_dir=args.output_dir)
        return


if __name__ == "__main__":
    main()
