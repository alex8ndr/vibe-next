from __future__ import annotations

import sys
from pathlib import Path

import polars as pl


sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import genre_mapping
from genre_mapping import load_artist_genre_lookup


def test_load_artist_genre_lookup_respects_configured_source_order(tmp_path, monkeypatch):
    """Earlier sources in get_genre_sources should win per normalized artist name."""
    src_a = tmp_path / "src_a.parquet"
    src_b = tmp_path / "src_b.parquet"

    df_a = pl.DataFrame(
        {
            "id": ["a1", "a2"],
            "name": ["Shared Artist", "Only A"],
            "popularity": [50, 40],
            "genres": [["rock"], ["jazz"]],
            "fallback": [None, None],
        }
    )
    df_b = pl.DataFrame(
        {
            "id": ["b1", "b2"],
            "name": ["Shared Artist", "Only B"],
            "popularity": [99, 30],
            "genres": [["hip hop"], ["metal"]],
            "fallback": [None, None],
        }
    )
    df_a.write_parquet(src_a)
    df_b.write_parquet(src_b)

    class _Source:
        def __init__(self, name: str, path: Path):
            self.name = name
            self.path = path

    monkeypatch.setattr(
        genre_mapping,
        "get_genre_sources",
        lambda: (_Source("first", src_a), _Source("second", src_b)),
    )

    lookup, lang_lookup = load_artist_genre_lookup()
    assert lookup["shared artist"] == "rock"
    assert lookup["only a"] == "jazz"
    assert lookup["only b"] == "metal"
    assert lang_lookup == {}
