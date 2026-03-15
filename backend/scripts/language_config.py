"""Shared language policy constants for the discovery/processing pipeline."""

from __future__ import annotations

# Genre-based language overrides used in Pass 2 language resolution.
# These are scene-level genres where language is intrinsic to the genre cluster.
GENRE_LANG_OVERRIDES: dict[str, str] = {
    "k-pop": "ko",
    "sertanejo": "pt",
    "j-pop": "ja",
    "j-rock": "ja",
    "cantopop": "zh",
    "schlager": "de",
    "forro": "pt",
    "samba": "pt",
    "funk": "pt",
    "tango": "es",
    "salsa": "es",
    "flamenco": "es",
    "corrido": "es",
}

# Pass 2 language resolution thresholds.
# - If tag_lang exists: prefer FastText only when confidence >= TAG_FASTTEXT_THRESHOLD.
# - If no tag_lang: default to en, but allow confident override if confidence >= FALLBACK_FASTTEXT_THRESHOLD.
TAG_FASTTEXT_THRESHOLD: float = 0.5
FALLBACK_FASTTEXT_THRESHOLD: float = 0.9
