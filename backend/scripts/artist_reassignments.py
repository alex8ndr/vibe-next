import os
from pathlib import Path

def load_reassignments() -> dict[str, list[str]]:
    """
    Dynamically load genre reassignments from .txt files in backend/data/reassignments.
    Each file should be named {genre}.txt and contain one artist per line.
    Lines starting with # and empty lines are ignored.
    """
    reassignments = {}
    # Get the directory relative to this script
    base_dir = Path(__file__).parent.parent / "data" / "reassignments"
    
    if not base_dir.exists():
        return {}

    for file_path in base_dir.glob("*.txt"):
        genre = file_path.stem
        artists = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        artists.append(line)
            if artists:
                reassignments[genre] = artists
        except Exception as e:
            print(f"Error loading reassignments from {file_path}: {e}")
            
    return reassignments

# Core dictionary used by process_data.py and filter_data.py
GENRE_REASSIGNMENTS: dict[str, list[str]] = load_reassignments()

def get_reassigned_artists() -> set[str]:
    """Return set of all artists that have genre reassignments."""
    artists = set()
    for artist_list in GENRE_REASSIGNMENTS.values():
        artists.update(artist_list)
    return artists

def get_artist_genre(artist_name: str) -> str | None:
    """Get reassigned genre for an artist, or None if not reassigned."""
    for genre, artists in GENRE_REASSIGNMENTS.items():
        if artist_name in artists:
            return genre
    return None
