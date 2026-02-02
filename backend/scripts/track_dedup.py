"""
Shared track deduplication logic for Vibe.

Simple approach: variants ADD to the original name, they don't replace it.
So we detect variants by checking if one track name is a prefix of another.
"""
import polars as pl

# Delimiters that separate base name from variant info
VARIANT_DELIMITERS = (' - ', ' (', ' [', ' /', ' –', ' —')


def _normalize_quotes(name: str) -> str:
    """Normalize quote characters."""
    name = name.replace(''', "'").replace(''', "'").replace('"', '"').replace('"', '"')
    name = name.replace('`', "'").replace('´', "'")
    return name


def normalize_track_name(name: str) -> str:
    """Normalize track name to base form (strip variant suffixes)."""
    if not name:
        return ""
    
    name = _normalize_quotes(name)
    name = ' '.join(name.lower().split())
    
    # Strip everything after the first variant delimiter
    for delim in VARIANT_DELIMITERS:
        if delim in name:
            name = name.split(delim)[0]
    
    return name.strip()


def deduplicate_tracks(
    df,
    track_col: str = "track_name",
    artist_col: str | None = None,
    prioritize_originals: bool = True,
):
    """
    Deduplicate tracks by detecting variants (tracks that extend another track's name).
    
    Args:
        df: pandas or polars DataFrame
        track_col: Column containing track names
        artist_col: If set, deduplicate within each artist (not globally)
        prioritize_originals: If True, keep original (shortest) over variants
    
    Returns:
        Deduplicated DataFrame (same type as input)
    """
    if isinstance(df, pl.DataFrame):
        return _dedupe_polars(df, track_col, artist_col, prioritize_originals)
    else:
        return _dedupe_pandas(df, track_col, artist_col, prioritize_originals)


def _dedupe_pandas(df, track_col, artist_col, prioritize_originals):
    """Pandas implementation - simple groupby on normalized name."""
    if track_col not in df.columns or df.empty:
        return df
    
    df = df.copy()
    
    # Normalize track names (strips variant suffixes)
    df["_norm"] = df[track_col].astype(str).apply(normalize_track_name)
    
    # Sort so that originals (shorter names, higher popularity) come first
    sort_cols = []
    sort_asc = []
    if prioritize_originals:
        df["_len"] = df[track_col].astype(str).str.len()
        sort_cols.append("_len")
        sort_asc.append(True)
    if "popularity" in df.columns:
        sort_cols.append("popularity")
        sort_asc.append(False)
    
    if sort_cols:
        # Convert float16 columns to float32 (pandas doesn't support float16 in sort)
        for col in sort_cols:
            if col in df.columns and df[col].dtype == "float16":
                df[col] = df[col].astype("float32")
        df = df.sort_values(sort_cols, ascending=sort_asc)
    
    # Deduplicate: keep first occurrence of each (artist, normalized_name)
    subset = ["_norm", artist_col] if artist_col and artist_col in df.columns else ["_norm"]
    df = df.drop_duplicates(subset=subset, keep="first")
    
    # Clean up temp columns
    drop_cols = ["_norm"]
    if "_len" in df.columns:
        drop_cols.append("_len")
    
    return df.drop(columns=drop_cols)


def _dedupe_polars(df: pl.DataFrame, track_col: str, artist_col: str | None, prioritize_originals: bool):
    """Polars implementation."""
    if df.is_empty() or track_col not in df.columns:
        return df
    
    # Convert to pandas for the grouping logic, then back
    # (Polars doesn't have great support for this kind of row-wise grouping)
    pdf = df.to_pandas()
    result_pdf = _dedupe_pandas(pdf, track_col, artist_col, prioritize_originals)
    return pl.from_pandas(result_pdf)



