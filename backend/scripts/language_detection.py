"""Shared FastText language detection utilities (NumPy 2.x compatible)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import numpy as np

_STRIP_TOKENS_RE = re.compile(
    r"\b(?:feat\.?|ft\.?|remix|edit|live|version|remaster(?:ed)?|"
    r"radio\s*edit|deluxe|bonus\s*track|original\s*mix|extended\s*mix|"
    r"acoustic\s*version|instrumental)\b",
    re.IGNORECASE,
)


def load_fasttext_model(model_path: Path | None = None):
    """Load FastText lid.176 model with a NumPy 2.x-safe predict monkey patch."""
    if not hasattr(np, "float_"):
        np.float_ = np.float64

    import fasttext.FastText as _ft_mod

    source = inspect.getsource(_ft_mod._FastText.predict)
    if "copy=False" in source:

        def _patched_predict(self, text, k=1, threshold=0.0, on_unicode_error="strict"):
            result = self.f.predict(text, k, threshold, on_unicode_error)
            if isinstance(text, list):
                labels = [[r[1] for r in row] for row in result]
                probs = [np.asarray([r[0] for r in row]) for row in result]
            else:
                labels = [r[1] for r in result]
                probs = np.asarray([r[0] for r in result])
            return labels, probs

        _ft_mod._FastText.predict = _patched_predict

    import fasttext

    if model_path is None:
        model_path = Path(__file__).parent.parent / "data" / "lid.176.ftz"

    if not model_path.exists():
        raise FileNotFoundError(f"FastText model not found: {model_path}")

    return fasttext.load_model(str(model_path))


def clean_track_title(title: str) -> str:
    """Strip noisy suffix/prefix tokens from a track title for language detection."""
    cleaned = _STRIP_TOKENS_RE.sub("", title)
    cleaned = re.sub(r"\([^)]*\)$", "", cleaned)
    return cleaned.strip()


def detect_language(model, text: str) -> tuple[str | None, float]:
    """Return (iso_code, confidence) from FastText for free text input."""
    clean = text.replace("\n", " ").strip()
    if not clean:
        return None, 0.0

    labels, probs = model.predict(clean)
    if not labels:
        return None, 0.0

    code = labels[0].replace("__label__", "")
    conf = float(probs[0]) if len(probs) else 0.0
    if not code:
        return None, conf

    return code, conf
