"""Resolve which datasets to use as primary (trusted) vs merge (external)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from paths import get_selectable_track_datasets, get_added_artists, get_input_dataset


@dataclass(frozen=True)
class DatasetResolution:
    """Result of resolving dataset selection into concrete paths."""
    input_path: Path
    merge_paths: list[Path]
    selected_names: list[str]
    primary_name: str
    added_artists_path: Path | None


def get_selectable_datasets() -> dict[str, Path]:
    """Get datasets available for selection (excludes added_artists)."""
    return get_selectable_track_datasets()


def resolve_filter_inputs(
    *,
    input_path: Path | None = None,
    merge_paths: list[Path] | None = None,
    datasets: list[str] | None = None,
    all_datasets: bool = False,
    exclude_datasets: list[str] | None = None,
    primary_dataset: str | None = None,
) -> DatasetResolution:
    """Resolve CLI arguments into concrete primary + merge paths.

    Two modes (mutually exclusive):
    - Path mode: explicit -i/--merge paths
    - Dataset-name mode: --datasets or --all-datasets

    Primary selection (dataset-name mode):
    - If --primary-dataset is set, use that exact name
    - Otherwise pick the largest file by size

    added_artists is always auto-included in merge_paths if it exists on disk.
    """
    added_artists_path = get_added_artists()

    if (input_path or merge_paths) and (datasets or all_datasets):
        raise ValueError(
            "Cannot combine --input/--merge with --datasets/--all-datasets"
        )

    if datasets or all_datasets:
        # Dataset-name mode
        available = get_selectable_datasets()

        if datasets:
            selected_names = []
            selected_paths = []
            for name in datasets:
                if name not in available:
                    avail_str = ", ".join(sorted(available.keys()))
                    raise ValueError(f"Unknown dataset: {name}. Available: {avail_str}")
                selected_names.append(name)
                selected_paths.append(available[name])
        else:
            exclude = set(exclude_datasets or [])
            selected_names = [n for n in available if n not in exclude]
            selected_paths = [available[n] for n in selected_names]

        if not selected_paths:
            raise ValueError("No datasets selected.")

        # Determine primary
        if primary_dataset:
            if primary_dataset not in selected_names:
                raise ValueError(
                    f"--primary-dataset '{primary_dataset}' not in selected datasets: "
                    f"{', '.join(selected_names)}"
                )
            primary_idx = selected_names.index(primary_dataset)
        else:
            # Pick largest file as primary
            sizes = []
            for p in selected_paths:
                try:
                    sizes.append(p.stat().st_size)
                except OSError:
                    sizes.append(0)
            primary_idx = sizes.index(max(sizes))

        # Move primary to front
        primary_name = selected_names[primary_idx]
        primary_path = selected_paths[primary_idx]
        remaining_names = [n for i, n in enumerate(selected_names) if i != primary_idx]
        remaining_paths = [p for i, p in enumerate(selected_paths) if i != primary_idx]

        resolved_input = primary_path
        resolved_merge = remaining_paths
        resolved_names = [primary_name] + remaining_names
    else:
        # Path mode
        if input_path:
            resolved_input = input_path
        else:
            resolved_input = get_input_dataset()

        resolved_merge = list(merge_paths) if merge_paths else []
        resolved_names = [resolved_input.stem]
        primary_name = resolved_names[0]

        # Return early with just the explicit paths + added_artists
        if added_artists_path:
            resolved_paths = {p.resolve() for p in resolved_merge}
            if added_artists_path.resolve() not in resolved_paths:
                resolved_merge.insert(0, added_artists_path)

        return DatasetResolution(
            input_path=resolved_input,
            merge_paths=resolved_merge,
            selected_names=resolved_names,
            primary_name=primary_name,
            added_artists_path=added_artists_path,
        )

    # Auto-include added_artists in merge paths (dataset-name mode)
    if added_artists_path:
        resolved_paths = {p.resolve() for p in resolved_merge}
        if added_artists_path.resolve() not in resolved_paths:
            resolved_merge.insert(0, added_artists_path)

    return DatasetResolution(
        input_path=resolved_input,
        merge_paths=resolved_merge,
        selected_names=resolved_names,
        primary_name=primary_name,
        added_artists_path=added_artists_path,
    )


def add_dataset_selection_args(parser) -> None:
    """Add dataset selection CLI arguments to an argparse parser.
    
    Shared between filter_data.py and run_pipeline.py for consistency.
    """
    available = get_selectable_datasets()
    group = parser.add_argument_group("dataset selection")
    group.add_argument(
        "--datasets",
        nargs="+",
        help=(
            "Select specific datasets by name. "
            "Available: " + ", ".join(sorted(available.keys()))
        ),
    )
    group.add_argument(
        "--all-datasets",
        action="store_true",
        help="Include all available datasets (core + external)",
    )
    group.add_argument(
        "--exclude-datasets",
        nargs="+",
        help="Exclude specific datasets by name (use with --all-datasets)",
    )
    group.add_argument(
        "--primary-dataset",
        type=str,
        default=None,
        help="Exact dataset name to use as primary/trusted input (default: largest file)",
    )
