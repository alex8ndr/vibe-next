"""
Shared track and artist deduplication logic for Vibe.

Track deduplication:
- Normalizes track names (lowercase, Unicode normalization, variant stripping)
- Detects variants by checking if one track name is a prefix of another
- Keeps highest-popularity version

Artist deduplication:
- Case-insensitive matching
- Unicode normalization (accents, special chars)
- Handles "The" prefix variations
"""
import re
import unicodedata
import polars as pl

# Delimiters that separate base name from variant info
VARIANT_DELIMITERS = (' - ', ' (', ' [', ' /', ' –', ' —')

# Words to strip from track names when normalizing
TRACK_NOISE_WORDS = {
    'remaster', 'remastered', 'remix', 'remixed', 'version', 'edit',
    'live', 'acoustic', 'demo', 'radio', 'single', 'album', 'extended',
    'original', 'mix', 'instrumental', 'feat', 'featuring', 'ft',
}


def _normalize_unicode(text: str) -> str:
    """Normalize Unicode characters (NFD decomposition, strip accents)."""
    # NFD decomposition separates base characters from combining marks
    normalized = unicodedata.normalize('NFD', text)
    # Remove combining marks (accents)
    stripped = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return stripped


def _normalize_quotes(name: str) -> str:
    """Normalize quote characters."""
    name = name.replace(''', "'").replace(''', "'").replace('"', '"').replace('"', '"')
    name = name.replace('`', "'").replace('´', "'")
    return name


def normalize_artist_name(name: str) -> str:
    """
    Normalize artist name for case-insensitive, accent-insensitive matching.
    
    Handles:
    - Case: "RADIOHEAD" == "Radiohead"
    - Accents: "Björk" == "Bjork"
    - "The" prefix: "The Beatles" == "Beatles"
    - Whitespace: "  Artist  Name  " == "Artist Name"
    """
    if not name:
        return ""
    
    name = _normalize_unicode(name)
    name = _normalize_quotes(name)
    name = name.lower().strip()
    
    # Normalize whitespace
    name = ' '.join(name.split())
    
    # Remove "the " prefix for matching purposes
    if name.startswith('the '):
        name = name[4:]
    
    return name


def normalize_track_name(name: str) -> str:
    """
    Normalize track name to base form for deduplication.
    
    Handles:
    - Case: "SONG NAME" == "Song Name"  
    - Accents: "Señorita" == "Senorita"
    - Variant suffixes: "Song (Remastered)" → "Song"
    - Live/remix markers in parentheses
    """
    if not name:
        return ""
    
    name = _normalize_unicode(name)
    name = _normalize_quotes(name)
    name = ' '.join(name.lower().split())
    
    # Strip everything after the first variant delimiter
    for delim in VARIANT_DELIMITERS:
        if delim in name:
            name = name.split(delim)[0]
    
    # Strip apostrophes for dedup ("you're" == "youre")
    name = name.replace("'", "")
    
    return name.strip()


def normalize_track_name_aggressive(name: str) -> str:
    """
    More aggressive normalization for catching near-duplicates.
    
    Also removes:
    - Common noise words (remaster, remix, live, etc.)
    - All punctuation
    - Feature credits
    """
    name = normalize_track_name(name)
    
    # Remove punctuation
    name = re.sub(r'[^\w\s]', '', name)
    
    # Remove noise words
    words = name.split()
    words = [w for w in words if w not in TRACK_NOISE_WORDS]
    
    return ' '.join(words)


def _strip_accents_expr(expr: pl.Expr) -> pl.Expr:
    """
    Strip accents/diacritics from a Polars string expression.
    
    Note: This uses explicit character replacements rather than NFD decomposition
    like the Python _normalize_unicode(). It covers common Latin accented characters
    (à, é, ñ, ö, etc.) but may miss some rare Unicode combining marks. For music
    artist/track names this coverage is sufficient.
    """
    return (
        expr
        .str.replace_all(r'[àáâãäåāăą]', 'a', literal=False)
        .str.replace_all(r'[èéêëēĕėęě]', 'e', literal=False)
        .str.replace_all(r'[ìíîïĩīĭįı]', 'i', literal=False)
        .str.replace_all(r'[òóôõöōŏőø]', 'o', literal=False)
        .str.replace_all(r'[ùúûüũūŭůűų]', 'u', literal=False)
        .str.replace_all(r'[ýÿŷ]', 'y', literal=False)
        .str.replace_all(r'[ñń]', 'n', literal=False)
        .str.replace_all(r'[çćĉċč]', 'c', literal=False)
        .str.replace_all(r'[šśŝş]', 's', literal=False)
        .str.replace_all(r'[žźż]', 'z', literal=False)
        .str.replace_all(r'[ðđ]', 'd', literal=False)
        .str.replace_all(r'[æ]', 'ae', literal=False)
        .str.replace_all(r'[œ]', 'oe', literal=False)
        .str.replace_all(r'[ß]', 'ss', literal=False)
        .str.replace_all(r'[þ]', 'th', literal=False)
    )


def artist_norm_expr(col: str = "artist_name") -> pl.Expr:
    """
    Polars expression for artist name normalization.
    Matches normalize_artist_name() Python function behavior.
    """
    return _strip_accents_expr(
        pl.col(col)
        .str.to_lowercase()
        .str.replace_all(r"['`´'']", "'", literal=False)  # normalize quotes
        .str.replace_all(r'[""]', '"', literal=False)     # normalize double quotes
        .str.strip_chars()
        .str.replace_all(r'\s+', ' ', literal=False)      # normalize whitespace
        .str.replace(r'^the\s+', '', literal=False)       # strip "the " prefix
    )


def track_norm_expr(col: str = "track_name") -> pl.Expr:
    """
    Polars expression for track name normalization.
    Matches normalize_track_name() Python function behavior.
    """
    return _strip_accents_expr(
        pl.col(col)
        .str.to_lowercase()
        .str.replace_all(r"['`´'']", "'", literal=False)
        .str.replace_all(r'[""]', '"', literal=False)
        .str.strip_chars()
        .str.replace_all(r'\s+', ' ', literal=False)
        # Strip variant suffixes: ( [ / - – —
        .str.replace(r'\s*[\(\[/–—].*$', '', literal=False)
        .str.replace(r'\s+-\s+.*$', '', literal=False)
        .str.replace_all("'", "", literal=True)  # strip apostrophes for dedup
        .str.strip_chars()
    )


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


def deduplicate_tracks_polars(df: pl.DataFrame, track_col: str = "track_name", artist_col: str = "artist_name") -> pl.DataFrame:
    """
    Pure Polars deduplication: keep highest-popularity track per (normalized_artist, normalized_track).
    
    This avoids Pandas conversion entirely.
    
    Strategy:
    1. Create normalized artist name (lowercase, strip accents, handle "the" prefix)
    2. Create normalized track name (lowercase, strip variant suffixes)
    3. Sort by popularity descending
    4. Keep first row per (norm_artist, norm_track) group
    
    This handles:
    - Case insensitivity: "RADIOHEAD" matches "Radiohead"
    - "The" variations: "The Beatles" matches "Beatles" 
    - Track variants: "Song (Remastered)" matches "Song"
    """
    if df.is_empty() or track_col not in df.columns:
        return df
    
    # Normalize track name using shared expression builder
    df = df.with_columns(track_norm_expr(track_col).alias("_norm_track"))
    
    # Normalize artist name (if column exists)
    if artist_col and artist_col in df.columns:
        df = df.with_columns(artist_norm_expr(artist_col).alias("_norm_artist"))
        subset = ["_norm_artist", "_norm_track"]
    else:
        subset = ["_norm_track"]
    
    # Sort by track name length ascending (prefer originals = shorter names),
    # then popularity descending as tiebreaker.
    df = df.with_columns(pl.col(track_col).str.len_chars().alias("_name_len"))
    sort_cols = ["_name_len"]
    sort_desc = [False]
    if "popularity" in df.columns:
        sort_cols.append("popularity")
        sort_desc.append(True)
    df = df.sort(sort_cols, descending=sort_desc)
    
    # Deduplicate: keep first occurrence of each (artist, normalized_name)
    df = df.unique(subset=subset, keep="first")
    
    # Clean up temp columns
    drop_cols = ["_norm_track", "_name_len"]
    if "_norm_artist" in df.columns:
        drop_cols.append("_norm_artist")
    
    return df.drop(drop_cols)

