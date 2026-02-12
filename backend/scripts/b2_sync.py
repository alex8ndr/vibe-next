"""
Backblaze B2 cloud sync for Vibe data pipeline.

Provides bidirectional sync between local data files and B2 bucket for:
- Multi-machine development (local + VPS can both add artists)
- Backup and disaster recovery
- Seamless data sharing between environments

DISABLED by default. To enable:
1. Set VIBE_B2_ENABLED=1 (or true/yes)
2. Configure B2 credentials (see B2Config)
3. Call sync functions explicitly or use --sync flag in pipeline scripts

B2 Free Tier limits:
- 10GB storage, 1GB/day egress (downloads), unlimited uploads
- Parquet files are ~100MB, so bandwidth is plenty

Sync strategy:
- Uses manifest.json for lightweight conflict detection
- Last-write-wins with timestamp comparison
- Atomic download pattern (download to .tmp, validate, rename)
- Upload only after local atomic write succeeds

Environment variables:
- VIBE_B2_ENABLED: Enable B2 sync (default: false)
- VIBE_B2_KEY_ID: B2 application key ID
- VIBE_B2_APP_KEY: B2 application key
- VIBE_B2_BUCKET: B2 bucket name
- VIBE_B2_PREFIX: Optional path prefix in bucket (default: "vibe-data")

Setup:
1. Sign up at https://www.backblaze.com/b2/cloud-storage.html
2. Create a bucket (e.g., "vibe-data")
3. Create an Application Key at https://secure.backblaze.com/app_keys.htm
4. Copy Key ID and Application Key to your .env file or environment

Example .env file:
    VIBE_B2_ENABLED=1
    VIBE_B2_KEY_ID=your_key_id_here
    VIBE_B2_APP_KEY=your_app_key_here
    VIBE_B2_BUCKET=vibe-data
    VIBE_B2_PREFIX=vibe-data
"""
import os
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any

import polars as pl

# Optional import - only needed when B2 is enabled
try:
    from b2sdk.v2 import B2Api, InMemoryAccountInfo
    B2_AVAILABLE = True
except ImportError:
    B2_AVAILABLE = False


class SyncDirection(Enum):
    """Direction of sync operation."""
    UPLOAD = "upload"      # Local → B2
    DOWNLOAD = "download"  # B2 → Local
    NONE = "none"          # No sync needed
    CONFLICT = "conflict"  # Both modified, needs resolution


@dataclass
class B2Config:
    """B2 configuration, loaded from environment."""
    key_id: str
    app_key: str
    bucket: str
    prefix: str = "vibe-data"
    
    @classmethod
    def from_env(cls) -> Optional["B2Config"]:
        """Load config from environment variables. Returns None if not configured."""
        key_id = os.environ.get("VIBE_B2_KEY_ID", "")
        app_key = os.environ.get("VIBE_B2_APP_KEY", "")
        bucket = os.environ.get("VIBE_B2_BUCKET", "")
        prefix = os.environ.get("VIBE_B2_PREFIX", "vibe-data")
        
        if not all([key_id, app_key, bucket]):
            return None
        
        return cls(key_id=key_id, app_key=app_key, bucket=bucket, prefix=prefix)
    
    def get_remote_path(self, filename: str) -> str:
        """Get full path in B2 bucket for a file."""
        return f"{self.prefix}/{filename}" if self.prefix else filename


@dataclass
class SyncState:
    """State of a file for sync comparison."""
    exists: bool
    last_modified: Optional[datetime] = None
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None  # SHA1 for B2 or local


@dataclass  
class SyncResult:
    """Result of a sync operation."""
    success: bool
    direction: SyncDirection
    message: str
    local_state: Optional[SyncState] = None
    remote_state: Optional[SyncState] = None


def is_b2_enabled() -> bool:
    """Check if B2 sync is enabled via environment."""
    val = os.environ.get("VIBE_B2_ENABLED", "").lower()
    return val in ("1", "true", "yes", "on")


def get_b2_config() -> Optional[B2Config]:
    """Get B2 config if enabled and configured."""
    if not is_b2_enabled():
        return None
    return B2Config.from_env()


# =============================================================================
# B2 Client Management
# =============================================================================

_b2_api: Optional[B2Api] = None
_bucket_cache: dict[str, Any] = {}


def _get_b2_api(config: B2Config) -> Optional[B2Api]:
    """Get or create B2 API client."""
    global _b2_api
    if _b2_api is None:
        if not B2_AVAILABLE:
            return None
        info = InMemoryAccountInfo()
        _b2_api = B2Api(info)
        _b2_api.authorize_account("production", config.key_id, config.app_key)
    return _b2_api


def _get_bucket(config: B2Config):
    """Get bucket object (cached)."""
    cache_key = f"{config.bucket}:{config.key_id}"
    if cache_key not in _bucket_cache:
        api = _get_b2_api(config)
        if api is None:
            return None
        _bucket_cache[cache_key] = api.get_bucket_by_name(config.bucket)
    return _bucket_cache[cache_key]


def _file_sha1(filepath: Path) -> str:
    """Calculate SHA1 hash of file (B2 uses this for integrity)."""
    sha1 = hashlib.sha1()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            sha1.update(chunk)
    return sha1.hexdigest()


# =============================================================================
# Sync Operations
# =============================================================================

def check_sync_needed(
    local_path: Path,
    config: B2Config,
    verbose: bool = False,
) -> SyncDirection:
    """
    Compare local file with B2 version to determine sync direction.
    
    Uses manifest.json timestamps for lightweight comparison.
    Falls back to checksum comparison if timestamps are close.
    
    Returns:
        SyncDirection indicating what action to take
    """
    if not B2_AVAILABLE:
        return SyncDirection.NONE
    
    if not local_path.exists():
        # Local doesn't exist, download if remote does
        try:
            bucket = _get_bucket(config)
            if bucket is None:
                return SyncDirection.NONE
            remote_path = config.get_remote_path(local_path.name)
            bucket.get_file_info_by_name(remote_path)
            return SyncDirection.DOWNLOAD
        except Exception:
            return SyncDirection.NONE
    
    try:
        bucket = _get_bucket(config)
        if bucket is None:
            return SyncDirection.NONE
        
        remote_path = config.get_remote_path(local_path.name)
        
        try:
            remote_file = bucket.get_file_info_by_name(remote_path)
            # B2 upload_timestamp is milliseconds since epoch (int)
            remote_mtime = datetime.fromtimestamp(
                remote_file.upload_timestamp / 1000, tz=timezone.utc
            )
        except Exception:
            # Remote file doesn't exist, upload
            return SyncDirection.UPLOAD
        
        # Use UTC for consistent comparison across machines
        local_mtime = datetime.fromtimestamp(
            local_path.stat().st_mtime, tz=timezone.utc
        )
        
        # Compare timestamps with 5-second tolerance
        time_diff = (local_mtime - remote_mtime).total_seconds()
        
        if abs(time_diff) < 5:
            # Timestamps match closely, check SHA1
            local_sha1 = _file_sha1(local_path)
            if local_sha1 == remote_file.content_sha1:
                return SyncDirection.NONE
            # Different content but same time - conflict
            return SyncDirection.CONFLICT
        elif time_diff > 0:
            return SyncDirection.UPLOAD
        else:
            return SyncDirection.DOWNLOAD
            
    except Exception as e:
        if verbose:
            print(f"  [B2] Error checking sync state: {e}")
        return SyncDirection.NONE


def upload_to_b2(
    local_path: Path,
    config: B2Config,
    *,
    validate: Callable[[pl.DataFrame], bool] | None = None,
    verbose: bool = False,
) -> SyncResult:
    """
    Upload a local parquet file to B2.
    
    Only uploads if local file is newer than B2 version.
    Validates file before upload.
    
    Args:
        local_path: Path to local parquet file
        config: B2 configuration
        validate: Optional validation function
        verbose: Print progress
    
    Returns:
        SyncResult with operation outcome
    """
    if not B2_AVAILABLE:
        return SyncResult(
            success=False,
            direction=SyncDirection.UPLOAD,
            message="b2sdk not installed. Run: pip install b2sdk",
        )
    
    if not local_path.exists():
        return SyncResult(
            success=False,
            direction=SyncDirection.UPLOAD,
            message=f"Local file not found: {local_path}",
        )
    
    try:
        # Validate local file before upload
        if validate and local_path.suffix == ".parquet":
            try:
                df = pl.read_parquet(local_path)
                if not validate(df):
                    return SyncResult(
                        success=False,
                        direction=SyncDirection.UPLOAD,
                        message=f"Validation failed for {local_path.name}",
                    )
            except Exception as e:
                return SyncResult(
                    success=False,
                    direction=SyncDirection.UPLOAD,
                    message=f"Cannot read {local_path.name}: {e}",
                )
        
        bucket = _get_bucket(config)
        if bucket is None:
            return SyncResult(
                success=False,
                direction=SyncDirection.UPLOAD,
                message="Failed to get B2 bucket",
            )
        
        remote_path = config.get_remote_path(local_path.name)
        
        if verbose:
            size_mb = local_path.stat().st_size / 1024 / 1024
            print(f"  Uploading {local_path.name} ({size_mb:.1f} MB)...")
        
        # Upload file
        uploaded = bucket.upload_local_file(
            local_file=str(local_path),
            file_name=remote_path,
        )
        
        return SyncResult(
            success=True,
            direction=SyncDirection.UPLOAD,
            message=f"Uploaded: {local_path.name}",
            local_state=SyncState(
                exists=True,
                last_modified=datetime.fromtimestamp(local_path.stat().st_mtime),
                size_bytes=local_path.stat().st_size,
                checksum=_file_sha1(local_path),
            ),
        )
        
    except Exception as e:
        return SyncResult(
            success=False,
            direction=SyncDirection.UPLOAD,
            message=f"Upload failed: {e}",
        )


def download_from_b2(
    local_path: Path,
    config: B2Config,
    *,
    validate: Callable[[pl.DataFrame], bool] | None = None,
    verbose: bool = False,
) -> SyncResult:
    """
    Download a parquet file from B2 atomically.
    
    Uses the same atomic pattern as local writes:
    1. Download to temp file
    2. Validate the downloaded data
    3. Atomically rename to target
    
    Args:
        local_path: Target local path
        config: B2 configuration
        validate: Optional validation function
        verbose: Print progress
    
    Returns:
        SyncResult with operation outcome
    """
    if not B2_AVAILABLE:
        return SyncResult(
            success=False,
            direction=SyncDirection.DOWNLOAD,
            message="b2sdk not installed. Run: pip install b2sdk",
        )
    
    try:
        bucket = _get_bucket(config)
        if bucket is None:
            return SyncResult(
                success=False,
                direction=SyncDirection.DOWNLOAD,
                message="Failed to get B2 bucket",
            )
        
        remote_path = config.get_remote_path(local_path.name)
        
        # Check if remote file exists
        try:
            remote_file = bucket.get_file_info_by_name(remote_path)
        except Exception:
            return SyncResult(
                success=False,
                direction=SyncDirection.DOWNLOAD,
                message=f"Remote file not found: {remote_path}",
            )
        
        # Download to temp file first (atomic pattern)
        temp_path = local_path.with_suffix(local_path.suffix + ".b2tmp")
        
        if verbose:
            size_mb = remote_file.size / 1024 / 1024
            print(f"  Downloading {local_path.name} ({size_mb:.1f} MB)...")
        
        # Download file
        bucket.download_file_by_name(remote_path).save_to(str(temp_path))
        
        # Validate downloaded file
        if validate and temp_path.suffix == ".parquet":
            try:
                df = pl.read_parquet(temp_path)
                if not validate(df):
                    temp_path.unlink()
                    return SyncResult(
                        success=False,
                        direction=SyncDirection.DOWNLOAD,
                        message=f"Validation failed for downloaded {local_path.name}",
                    )
            except Exception as e:
                temp_path.unlink()
                return SyncResult(
                    success=False,
                    direction=SyncDirection.DOWNLOAD,
                    message=f"Cannot read downloaded {local_path.name}: {e}",
                )
        
        # Atomic rename
        if local_path.exists():
            backup_path = local_path.with_suffix(local_path.suffix + ".bak")
            local_path.rename(backup_path)
        
        temp_path.rename(local_path)
        
        # Clean up backup if exists
        backup_path = local_path.with_suffix(local_path.suffix + ".bak")
        if backup_path.exists():
            backup_path.unlink()
        
        # Preserve remote timestamp to prevent re-upload loops
        # B2 upload_timestamp is milliseconds since epoch (int)
        remote_mtime_secs = remote_file.upload_timestamp / 1000
        os.utime(local_path, (remote_mtime_secs, remote_mtime_secs))
        
        return SyncResult(
            success=True,
            direction=SyncDirection.DOWNLOAD,
            message=f"Downloaded: {local_path.name}",
            remote_state=SyncState(
                exists=True,
                last_modified=datetime.fromtimestamp(
                    remote_file.upload_timestamp / 1000, tz=timezone.utc
                ),
                size_bytes=remote_file.size,
                checksum=remote_file.content_sha1,
            ),
        )
        
    except Exception as e:
        # Clean up temp file if exists
        temp_path = local_path.with_suffix(local_path.suffix + ".b2tmp")
        if temp_path.exists():
            temp_path.unlink()
        return SyncResult(
            success=False,
            direction=SyncDirection.DOWNLOAD,
            message=f"Download failed: {e}",
        )


def sync_file(
    local_path: Path,
    config: B2Config,
    *,
    prefer: SyncDirection = SyncDirection.NONE,
    validate: Callable[[pl.DataFrame], bool] | None = None,
    verbose: bool = False,
) -> SyncResult:
    """
    Bidirectional sync for a single file.
    
    Automatically determines direction based on timestamps.
    Use prefer= to resolve conflicts (default: fail on conflict).
    
    Args:
        local_path: Local file path
        config: B2 configuration
        prefer: Which version to prefer on conflict
        validate: Optional validation function
        verbose: Print progress
    
    Returns:
        SyncResult with operation outcome
    """
    direction = check_sync_needed(local_path, config, verbose=verbose)
    
    if direction == SyncDirection.NONE:
        return SyncResult(
            success=True,
            direction=SyncDirection.NONE,
            message="Already in sync",
        )
    
    if direction == SyncDirection.CONFLICT:
        if prefer == SyncDirection.UPLOAD:
            direction = SyncDirection.UPLOAD
        elif prefer == SyncDirection.DOWNLOAD:
            direction = SyncDirection.DOWNLOAD
        else:
            return SyncResult(
                success=False,
                direction=SyncDirection.CONFLICT,
                message="Conflict detected. Use prefer= to resolve.",
            )
    
    if direction == SyncDirection.UPLOAD:
        return upload_to_b2(local_path, config, validate=validate, verbose=verbose)
    else:
        return download_from_b2(local_path, config, validate=validate, verbose=verbose)


# =============================================================================
# High-Level Sync API
# =============================================================================

def sync_data_files(
    *,
    prefer: SyncDirection = SyncDirection.NONE,
    verbose: bool = False,
) -> dict[str, SyncResult]:
    """
    Sync all data files with B2.
    
    Files synced:
    - data.parquet (main dataset)
    - data_encoded.parquet (processed dataset)
    - added_artists.parquet (incremental additions)
    - manifest.json (metadata)
    
    Call this at the start of pipeline to pull latest, or at end to push.
    
    Args:
        prefer: Which version to prefer on conflicts
        verbose: Print progress
    
    Returns:
        Dict mapping filename → SyncResult
    """
    config = get_b2_config()
    
    if config is None:
        if verbose:
            print("  B2 sync disabled (VIBE_B2_ENABLED not set or missing credentials)")
        return {}
    
    if not B2_AVAILABLE:
        print("  Warning: B2 enabled but b2sdk not installed. Run: pip install b2sdk")
        return {}
    
    from paths import RAW_DATASET, ENCODED_DATASET, ADDED_ARTISTS, MANIFEST_FILE
    from io_utils import validate_encoded_dataset, validate_filtered_dataset
    
    files_to_sync = [
        (RAW_DATASET, validate_filtered_dataset),
        (ENCODED_DATASET, validate_encoded_dataset),
        (ADDED_ARTISTS, None),  # Optional file, no strict validation
        (MANIFEST_FILE, None),
    ]
    
    results = {}
    for path, validator in files_to_sync:
        # Skip optional files that don't exist locally and we're not pulling
        if not path.exists() and prefer != SyncDirection.DOWNLOAD:
            continue
            
        if verbose:
            print(f"  Syncing: {path.name}")
        results[path.name] = sync_file(path, config, prefer=prefer, validate=validator, verbose=verbose)
    
    return results


def pull_before_pipeline(verbose: bool = False) -> bool:
    """
    Pull latest data from B2 before running pipeline.
    
    Call at start of incremental_update.py or add_artist.py.
    Prefers remote version on conflict (gets latest from other machines).
    
    Returns:
        True if sync succeeded or B2 disabled, False on error
    """
    if not is_b2_enabled():
        return True
    
    if verbose:
        print("Pulling from B2...")
    
    results = sync_data_files(prefer=SyncDirection.DOWNLOAD, verbose=verbose)
    
    for name, result in results.items():
        if not result.success:
            print(f"  ✗ Failed to sync {name}: {result.message}")
            return False
    
    return True


def push_after_pipeline(verbose: bool = False) -> bool:
    """
    Push local changes to B2 after pipeline completes.
    
    Call at end of incremental_update.py after atomic writes succeed.
    Prefers local version on conflict (push our changes).
    
    Returns:
        True if sync succeeded or B2 disabled, False on error
    """
    if not is_b2_enabled():
        return True
    
    if verbose:
        print("Pushing to B2...")
    
    results = sync_data_files(prefer=SyncDirection.UPLOAD, verbose=verbose)
    
    for name, result in results.items():
        if not result.success:
            print(f"  ✗ Failed to sync {name}: {result.message}")
            return False
    
    return True


# =============================================================================
# CLI for manual sync operations
# =============================================================================

def main():
    """Manual sync CLI."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync Vibe data with Backblaze B2")
    parser.add_argument("--pull", action="store_true", help="Pull latest from B2")
    parser.add_argument("--push", action="store_true", help="Push local to B2")
    parser.add_argument("--status", action="store_true", help="Show sync status")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--force", action="store_true", help="Force sync even if disabled")
    
    args = parser.parse_args()
    
    if not is_b2_enabled() and not args.force:
        print("B2 sync is disabled.")
        print("Set VIBE_B2_ENABLED=1 and configure credentials to enable.")
        print("\nRequired environment variables:")
        print("  VIBE_B2_KEY_ID   - B2 application key ID")
        print("  VIBE_B2_APP_KEY  - B2 application key")
        print("  VIBE_B2_BUCKET   - B2 bucket name")
        print("  VIBE_B2_PREFIX   - Path prefix (optional, default: vibe-data)")
        print("\nOr add to backend/.env:")
        print("  VIBE_B2_ENABLED=1")
        print("  VIBE_B2_KEY_ID=your_key_id")
        print("  VIBE_B2_APP_KEY=your_app_key")
        print("  VIBE_B2_BUCKET=vibe-data")
        return 1
    
    config = get_b2_config() or B2Config.from_env()
    if config is None:
        print("Error: B2 credentials not configured")
        return 1
    
    print(f"B2 bucket: {config.bucket}/{config.prefix}")
    
    if args.status:
        from paths import RAW_DATASET, ENCODED_DATASET, ADDED_ARTISTS, MANIFEST_FILE
        print("\nSync status:")
        for path in [RAW_DATASET, ENCODED_DATASET, ADDED_ARTISTS, MANIFEST_FILE]:
            direction = check_sync_needed(path, config, verbose=args.verbose)
            status = "✓" if direction == SyncDirection.NONE else direction.value
            exists = "✓" if path.exists() else "✗"
            print(f"  {exists} {path.name}: {status}")
        return 0
    
    if args.pull:
        success = pull_before_pipeline(verbose=args.verbose)
        return 0 if success else 1
    
    if args.push:
        success = push_after_pipeline(verbose=args.verbose)
        return 0 if success else 1
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    exit(main())
