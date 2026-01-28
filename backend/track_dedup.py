"""
Shared track deduplication logic for Vibe.
"""
import re
import polars as pl

# Combined regex for variant suffixes (remixes, live, remastered, etc.)
_VARIANT_PATTERN = re.compile(
    r"""
    # Parenthetical variants: (Live at...), (2021 Remastered), (Acoustic Version), etc.
    \s*\([^)]*(?:live|remaster|acoustic|radio\s+edit|single\s+version|album\s+version|
    extended|edit|mono|stereo|bonus|deluxe|explicit|clean|censored|original|
    version|mix|instrumental|remix|demo|unplugged|stripped)[^)]*\)
    |
    # Dash variants: - Live, - 2021 Remastered, - Acoustic, etc.
    \s*[-–—]\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|live|acoustic(?:\s+version)?|
    radio\s+edit|single\s+version|album\s+version|extended(?:\s+mix)?|
    edit|instrumental|remix|demo)(?:\s+\d{4})?\s*$
    """,
    re.IGNORECASE | re.VERBOSE
)




def _normalize(name: str) -> str:
    """Normalize track name for comparison."""
    if not name:
        return ""
    result = _VARIANT_PATTERN.sub("", name.strip())
    result = " ".join(result.lower().split())
    return result.rstrip(" -–—:;,.")


def deduplicate_tracks(
    df,
    track_col: str = "track_name",
    artist_col: str | None = None,
    prioritize_originals: bool = True,
):
    """
    Deduplicate tracks by normalized name, keeping originals over variants.
    
    Args:
        df: pandas or polars DataFrame
        track_col: Column containing track names
        artist_col: If set, deduplicate within each artist (not globally)
        prioritize_originals: If True, keep original over remix even if remix is more popular
    
    Returns:
        Deduplicated DataFrame (same type as input)
    """
    if isinstance(df, pl.DataFrame):
        return _dedupe_polars(df, track_col, artist_col, prioritize_originals)
    else:
        return _dedupe_pandas(df, track_col, artist_col, prioritize_originals)


def _dedupe_pandas(df, track_col, artist_col, prioritize_originals):
    """Pandas implementation."""
    if track_col not in df.columns or df.empty:
        return df
    
    df = df.copy()
    
    # Vectorized normalization
    s = df[track_col].astype(str).str.strip()
    s = s.str.replace(_VARIANT_PATTERN, "", regex=True)
    s = s.str.lower().str.replace(r"\s+", " ", regex=True)
    df["_norm"] = s.str.rstrip(" -–—:;,.")
    
    if prioritize_originals:
        df["_var"] = df[track_col].astype(str).str.contains(_VARIANT_PATTERN, regex=True, na=False)
        sort_cols = ["_var", "popularity"] if "popularity" in df.columns else ["_var"]
        sort_asc = [True, False] if "popularity" in df.columns else [True]
        df = df.sort_values(sort_cols, ascending=sort_asc)
    elif "popularity" in df.columns:
        df = df.sort_values("popularity", ascending=False)
    
    subset = ["_norm", artist_col] if artist_col and artist_col in df.columns else ["_norm"]
    df = df.drop_duplicates(subset=subset, keep="first")
    
    drop_cols = ["_norm"] + (["_var"] if prioritize_originals else [])
    return df.drop(columns=drop_cols)


def _dedupe_polars(df, track_col, artist_col, prioritize_originals):
    """Polars implementation."""
    if track_col not in df.columns or df.is_empty():
        return df
    
    # Ensure track_col is string type (might be categorical from merged data)
    df = df.with_columns(pl.col(track_col).cast(pl.Utf8))
    
    # Normalize track names
    norm_expr = (
        pl.col(track_col)
        .str.strip_chars()
        .str.replace_all(_VARIANT_PATTERN.pattern, "")
        .str.to_lowercase()
        .str.replace_all(r"\s+", " ")
        .str.strip_chars(" -–—:;,.")
        .alias("_norm")
    )
    
    if prioritize_originals:
        var_expr = (
            pl.col(track_col)
            .str.contains(_VARIANT_PATTERN.pattern)
            .alias("_var")
        )
        df = df.with_columns([norm_expr, var_expr])
        
        sort_cols = ["_var", "popularity"] if "popularity" in df.columns else ["_var"]
        sort_desc = [False, True] if "popularity" in df.columns else [False]
        df = df.sort(sort_cols, descending=sort_desc)
    else:
        df = df.with_columns(norm_expr)
        if "popularity" in df.columns:
            df = df.sort("popularity", descending=True)
    
    subset = ["_norm", artist_col] if artist_col and artist_col in df.columns else ["_norm"]
    df = df.unique(subset=subset, maintain_order=True)
    
    drop_cols = ["_norm"] + (["_var"] if prioritize_originals else [])
    return df.drop(drop_cols)
