"""Shared language policy constants for the discovery/processing pipeline."""

from __future__ import annotations

# Genre-level language overrides.
GENRE_LANG_OVERRIDES: dict[str, str] = {
    "sertanejo": "pt",
    "schlager": "de",
    "forro": "pt",
    "samba": "pt",
    "funk": "pt",
    "tango": "es",
    "salsa": "es",
    "flamenco": "es",
    "corrido": "es",
}

# Language resolution thresholds.
TAG_FASTTEXT_THRESHOLD: float = 0.5
LOCALE_SIGNAL_FASTTEXT_THRESHOLD: float = 0.3
FALLBACK_FASTTEXT_THRESHOLD: float = 0.8
# Stronger override threshold for explicit CJK tag languages.
CJK_TAG_FASTTEXT_THRESHOLD: float = 0.9

PROTECTED_TAG_LANG_CODES: frozenset[str] = frozenset(
    {
        "ja",
        "ko",
        "zh",
        "hi",
        "ur",
        "pa",
        "bn",
        "ta",
        "te",
        "ml",
        "mr",
        "gu",
        "kn",
    }
)

# Shared resolver/debug defaults.
LANGUAGE_MAX_TITLES: int = 50

# Title-vote fallback when combined-title confidence is too low.
VOTE_FALLBACK_CONF_FLOOR: float = 0.5
VOTE_FALLBACK_MIN_VOTES: int = 5
VOTE_FALLBACK_DOMINANCE: float = 0.6
