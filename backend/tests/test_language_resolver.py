from __future__ import annotations

import sys
from pathlib import Path

import polars as pl


# Make pipeline modules importable in tests.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from pipeline.utils.language_resolver import resolve_artist_languages


class _FakeModel:
    pass


def test_protected_tag_language_is_not_overridden(monkeypatch):
    """Explicit protected tag languages (e.g. Hindi) must not be flipped by FastText."""

    def _fake_lookup(include_lang_signal=False):
        _ = include_lang_signal
        # tag_lang says Hindi, while simulated FastText says English.
        return ({}, {"khan bhaini": "hi"}, {"khan bhaini": True})

    def _fake_detect_language(_model, _text):
        return "en", 0.99

    monkeypatch.setattr(
        "pipeline.utils.language_resolver.load_artist_genre_lookup",
        _fake_lookup,
    )
    monkeypatch.setattr(
        "pipeline.utils.language_resolver.load_fasttext_model",
        lambda: _FakeModel(),
    )
    monkeypatch.setattr(
        "pipeline.utils.language_resolver.detect_language",
        _fake_detect_language,
    )

    df = pl.DataFrame(
        {
            "artist_name": ["Khan Bhaini", "Khan Bhaini"],
            "track_name": ["Track One", "Track Two"],
            "genre": ["pop", "pop"],
            "popularity": [0.8, 0.7],
        }
    )

    resolved = resolve_artist_languages(df, verbose=False)
    assert resolved["Khan Bhaini"] == "hi"


def test_non_protected_tag_language_can_be_overridden(monkeypatch):
    """Unprotected tag languages should still allow high-confidence FastText override."""

    def _fake_lookup(include_lang_signal=False):
        _ = include_lang_signal
        # tag_lang says French, but simulated FastText says English.
        return ({}, {"example artist": "fr"}, {"example artist": True})

    def _fake_detect_language(_model, _text):
        return "en", 0.99

    monkeypatch.setattr(
        "pipeline.utils.language_resolver.load_artist_genre_lookup",
        _fake_lookup,
    )
    monkeypatch.setattr(
        "pipeline.utils.language_resolver.load_fasttext_model",
        lambda: _FakeModel(),
    )
    monkeypatch.setattr(
        "pipeline.utils.language_resolver.detect_language",
        _fake_detect_language,
    )

    df = pl.DataFrame(
        {
            "artist_name": ["Example Artist", "Example Artist"],
            "track_name": ["Titre A", "Titre B"],
            "genre": ["pop", "pop"],
            "popularity": [0.8, 0.7],
        }
    )

    resolved = resolve_artist_languages(df, verbose=False)
    assert resolved["Example Artist"] == "en"


def test_protected_tag_language_with_region_suffix_is_not_overridden(monkeypatch):
    """Locale-form tags (e.g. hi-IN) should normalize to protected base language."""

    def _fake_lookup(include_lang_signal=False):
        _ = include_lang_signal
        return ({}, {"shreya ghoshal": "hi-IN"}, {"shreya ghoshal": True})

    def _fake_detect_language(_model, _text):
        return "en", 0.99

    monkeypatch.setattr(
        "pipeline.utils.language_resolver.load_artist_genre_lookup",
        _fake_lookup,
    )
    monkeypatch.setattr(
        "pipeline.utils.language_resolver.load_fasttext_model",
        lambda: _FakeModel(),
    )
    monkeypatch.setattr(
        "pipeline.utils.language_resolver.detect_language",
        _fake_detect_language,
    )

    df = pl.DataFrame(
        {
            "artist_name": ["Shreya Ghoshal", "Shreya Ghoshal"],
            "track_name": ["Song One", "Song Two"],
            "genre": ["pop", "pop"],
            "popularity": [0.8, 0.7],
        }
    )

    resolved = resolve_artist_languages(df, verbose=False)
    assert resolved["Shreya Ghoshal"] == "hi"
