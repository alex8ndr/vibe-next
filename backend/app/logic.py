"""
Recommendation logic for Vibe music recommendation app.
Updated to use polars instead of pandas for memory efficiency.
"""
import ctypes
import gc
import os
import numpy as np
import polars as pl
from pathlib import Path
from typing import Protocol
from time import perf_counter

FEATURE_WEIGHTS = {
    'popularity': 0.4,
    'year': 0.4,
    'duration_ms': 0.4,
    'acousticness': 1.2,
    'danceability': 1.2,
    'energy': 1.2,
    'valence': 1.2,
    'instrumentalness': 1.2,
    'speechiness': 1.0,
    'loudness': 1.0,
    'tempo': 1.0,
    'liveness': 1.0,
}

# Effective genre weight for each slider position (0=None, 1=Low, 2=Medium, 3=High, 4=Max)
GENRE_WEIGHT_CURVE = [0, 0.3, 0.8, 2.0, 5.0]

# Composite "vibe" dimensions that map to multiple audio features
# Each maps a -1 to +1 slider to feature offsets
# Format: { 'feature_name': weight } - positive weight = feature increases with slider
VIBE_DIMENSIONS = {
    # Chill (-1) to Intense (+1): affects energy, danceability, tempo, loudness
    'mood': {
        'energy': 1.0,
        'loudness': 0.2,
        'danceability': 0.0,
        'valence': 0.0,
    },
    # Acoustic (-1) to Electronic (+1): affects acousticness (inverted), instrumentalness
    'sound': {
        'acousticness': -0.8,  # Negative = acoustic decreases as slider goes up
        'speechiness': -0.2,
        'danceability': 0.4,
        'instrumentalness': 0.1,
    },
}

# How strongly vibe sliders affect the search (in feature units, 0-1 scale)
VIBE_SLIDER_STRENGTH = 0.8

# How many top tracks to consider for diversity sampling 
DIVERSITY_CANDIDATE_MULTIPLIER = 3

# Number of tracks to recommend per artist
TRACKS_PER_ARTIST = 3

# Genre focus slider (0-4: None/Low/Medium/High/Max)
GENRE_FOCUS = 2

# Variety/diversity level (0-3: None/Low/Medium/High)
VARIETY = 0

# Max artists to return
MAX_ARTISTS = 6

# Noise strength for variety control (easy to tune)
VARIETY_NOISE_SCALE = 0.1  # Higher = more randomness

# Sample size for Gumbel noise distribution
SAMPLE_SIZE = 5000

# ANN overfetch multiplier: fetch K*ANN_OVERFETCH candidates from audio-only ANN
ANN_OVERFETCH = 20

# Limit temporary query allocations when scanning the full audio matrix.
# Each batch allocates roughly `batch_size * n_tracks * 4 bytes` for the
# temporary squared-distance buffer before reducing to a single min vector.
AUDIO_CANDIDATE_BATCH_SEEDS = 4

# Spotify track IDs are typically 22 bytes; keep a lower bound so the lookup
# array stays fixed-width and compact even on tiny dev fixtures.
MIN_TRACK_ID_BYTES = 22


def _trim_process_memory() -> None:
    """Best-effort memory trim after large startup allocations.

    Linux/glibc can return freed arenas to the OS via `malloc_trim(0)`. On
    non-glibc platforms this quietly becomes a no-op.
    """
    gc.collect()
    if os.name != 'posix':
        return
    try:
        libc = ctypes.CDLL(None)
        trim = getattr(libc, 'malloc_trim', None)
        if trim is not None:
            trim(0)
    except Exception:
        pass


class DataSource(Protocol):
    def get_column_names(self) -> list[str]:
        ...

    def load(self, columns: list[str] | None = None) -> pl.DataFrame:
        ...


class ParquetDataSource:
    def __init__(self, path: Path):
        self.path = path

    def get_column_names(self) -> list[str]:
        return pl.scan_parquet(self.path).collect_schema().names()
    
    def load(self, columns: list[str] | None = None) -> pl.DataFrame:
        if columns:
            return pl.scan_parquet(self.path).select(columns).collect()
        return pl.read_parquet(self.path)


class MusicData:
    def __init__(self, source: DataSource):
        self.source = source
        self.df: pl.DataFrame | None = None
        self.matrix_audio: np.ndarray | None = None
        self.matrix_genre: np.ndarray | None = None
        self.audio_norms_sq: np.ndarray | None = None  # Precomputed ||x||² for fast distance
        self.genre_norms: np.ndarray | None = None  # Precomputed genre vector norms
        self.artists_list: list[str] = []
        self.artist_names_by_code: list[str] = []
        self.artist_name_to_code: dict[str, int] = {}
        self.audio_cols: list[str] = []
        self.audio_col_indices: dict[str, int] = {}
        self.genre_cols: list[str] = []
        self.track_ids_sorted: np.ndarray | None = None
        self.track_row_indices_sorted: np.ndarray | None = None
        self.track_sorted_pos_by_row: np.ndarray | None = None
        self.track_id_dtype: np.dtype | None = None
        self.track_artist_codes: np.ndarray | None = None  # Per-track compact artist code
        self.artist_popularity_by_code: np.ndarray | None = None  # Per-artist popularity (0-1)
        self.artist_track_count_by_code: np.ndarray | None = None  # Per-artist log track count (0-1)
        self.popularity_median: float = 0.5  # Median artist popularity for centering
        # Debug cache is filled lazily, only when debug mode is requested.
        self.genre_profile_cache: dict[str, list[tuple[str, float]]] = {}
    
    def load(self) -> None:
        t0 = perf_counter()
        print("[startup] Inspecting parquet schema...")
        all_columns = self.source.get_column_names()

        required = ['artist_name', 'track_name', 'track_id']
        for col in required:
            if col not in all_columns:
                raise ValueError(f"Missing required column: {col}")

        self.genre_cols = [c for c in all_columns if c.startswith('genre_')]
        self.audio_cols = [c for c in FEATURE_WEIGHTS.keys() if c in all_columns]
        self.audio_col_indices = {col: idx for idx, col in enumerate(self.audio_cols)}

        meta_cols = required[:]
        for col in ['popularity', 'genre']:
            if col in all_columns and col not in meta_cols:
                meta_cols.append(col)

        print(
            f"[startup] Loading metadata ({len(meta_cols)} cols), audio ({len(self.audio_cols)} cols), "
            f"and genre ({len(self.genre_cols)} cols) separately..."
        )
        meta_df = self.source.load(meta_cols)
        print(f"[startup] Loaded parquet rows: {len(meta_df):,}")
        
        # Filter out rows with null required fields (data quality safeguard)
        valid_mask = np.ones(len(meta_df), dtype=bool)
        for col in required:
            col_mask = meta_df[col].is_not_null().to_numpy()
            null_count = int((~col_mask).sum())
            if null_count > 0:
                print(f"Warning: Filtering {null_count} rows with null {col}")
                valid_mask &= col_mask

        if not valid_mask.all():
            meta_df = meta_df.filter(pl.Series(valid_mask))

        artist_catalog = (
            meta_df.select('artist_name')
            .unique(maintain_order=True)
            .with_row_index('artist_code')
        )
        self.artist_names_by_code = artist_catalog['artist_name'].to_list()
        self.artist_name_to_code = {
            artist: int(code)
            for artist, code in zip(
                self.artist_names_by_code,
                artist_catalog['artist_code'].to_list(),
            )
        }

        meta_df = (
            meta_df.join(artist_catalog, on='artist_name', how='left')
            .with_row_index('row_idx')
        )

        self.track_artist_codes = (
            meta_df['artist_code']
            .cast(pl.UInt32)
            .to_numpy()
            .astype(np.uint32, copy=False)
        )
        self._build_track_lookup(meta_df['track_id'])

        print(f"[startup] Building audio matrix ({len(self.audio_cols)} cols)...")
        
        # Audio Matrix (Weighted for Euclidean)
        audio_df = self.source.load(self.audio_cols)
        audio_data = audio_df.to_numpy().astype(np.float32, copy=False)
        if not valid_mask.all():
            audio_data = audio_data[valid_mask]
        weights = np.array([FEATURE_WEIGHTS[c] for c in self.audio_cols], dtype=np.float32)
        self.matrix_audio = audio_data * weights
        
        # Precompute squared norms for fast Euclidean distance
        self.audio_norms_sq = np.sum(self.matrix_audio ** 2, axis=1)
        
        # Genre Matrix (Unweighted for Cosine)
        genre_df = self.source.load(self.genre_cols)
        matrix_genre_f32 = genre_df.to_numpy().astype(np.float32, copy=False)
        if not valid_mask.all():
            matrix_genre_f32 = matrix_genre_f32[valid_mask]
        
        # Precompute genre norms 
        self.genre_norms = np.linalg.norm(matrix_genre_f32, axis=1).astype(np.float32)
        self.genre_norms[self.genre_norms == 0] = 1.0
        self.matrix_genre = matrix_genre_f32.astype(np.float16)
        del matrix_genre_f32
        
        audio_mb = self.matrix_audio.nbytes / 1024**2
        genre_mb = self.matrix_genre.nbytes / 1024**2
        print(f"[startup] Matrices ready (audio {audio_mb:.0f}MB f32 + genre {genre_mb:.0f}MB f16)")
        
        # Sort artists by popularity
        artist_popularity = (
            meta_df.group_by('artist_name')
            .agg(pl.col('popularity').sum())
            .sort('popularity', descending=True)
        )
        self.artists_list = artist_popularity['artist_name'].to_list()
        print(f"[startup] Indexed {len(self.artists_list):,} artists by popularity")

        lookup_mb = (
            self.track_ids_sorted.nbytes
            + self.track_row_indices_sorted.nbytes
            + self.track_sorted_pos_by_row.nbytes
        ) / 1024**2
        print(f"[startup] Built compact track lookup ({lookup_mb:.0f}MB)")
        
        # Precompute artist-level popularity (avg track popularity per artist)
        self._build_artist_popularity(meta_df)
        
        # Keep metadata for display/lookup
        keep_exprs = [
            pl.col('row_idx').cast(pl.UInt32),
            pl.col('artist_code').cast(pl.UInt32),
            pl.col('track_name'),
        ]
        for col in ['popularity', 'genre']:
            if col in meta_df.columns:
                if col == 'popularity':
                    keep_exprs.append(pl.col(col).cast(pl.Float32))
                elif col == 'genre':
                    keep_exprs.append(pl.col(col).cast(pl.Categorical))

        self.df = meta_df.select(keep_exprs).rechunk()

        del artist_catalog, artist_popularity, meta_df, audio_df, genre_df, audio_data, weights, valid_mask
        _trim_process_memory()

        elapsed = perf_counter() - t0
        print(f"[startup] MusicData load complete in {elapsed:.2f}s")

    def _build_track_lookup(self, track_ids: pl.Series) -> None:
        """Build a compact, fixed-width sorted lookup for Spotify track IDs."""
        n_tracks = len(track_ids)
        max_len = max(
            MIN_TRACK_ID_BYTES,
            int(track_ids.str.len_bytes().max() or 1),
        )
        dtype = np.dtype(f'S{max_len}')

        encoded = np.fromiter(
            (track_id.encode('utf-8') for track_id in track_ids),
            dtype=dtype,
            count=n_tracks,
        )
        sorted_row_indices = np.argsort(encoded, kind='mergesort').astype(np.uint32, copy=False)
        sorted_positions = np.empty(n_tracks, dtype=np.uint32)
        sorted_positions[sorted_row_indices] = np.arange(n_tracks, dtype=np.uint32)

        self.track_id_dtype = dtype
        self.track_ids_sorted = encoded[sorted_row_indices]
        self.track_row_indices_sorted = sorted_row_indices
        self.track_sorted_pos_by_row = sorted_positions
    
    def _build_artist_popularity(self, df: pl.DataFrame) -> None:
        """Build per-artist popularity and track count arrays for the popularity slider."""
        # Compute mean popularity and track count per artist
        artist_stats = (
            df.group_by('artist_code')
            .agg([
                pl.col('popularity').cast(pl.Float32).mean().alias('avg_pop'),
                pl.len().alias('track_count')
            ])
            .sort('artist_code')
        )
        artist_codes = artist_stats['artist_code'].to_numpy().astype(np.int32, copy=False)
        avg_pops = artist_stats['avg_pop'].to_numpy().astype(np.float32, copy=False)
        track_counts = artist_stats['track_count'].to_numpy().astype(np.float32, copy=False)
        
        # Log-normalize track counts to 0-1 range
        log_counts = np.log1p(track_counts)
        max_log = log_counts.max()
        norm_counts = log_counts / max_log if max_log > 0 else log_counts

        # Store median for centering
        self.popularity_median = float(np.median(avg_pops)) if len(avg_pops) else 0.5

        n_artists = len(self.artist_names_by_code)
        self.artist_popularity_by_code = np.full(n_artists, self.popularity_median, dtype=np.float32)
        self.artist_track_count_by_code = np.full(n_artists, 0.5, dtype=np.float32)
        self.artist_popularity_by_code[artist_codes] = avg_pops
        self.artist_track_count_by_code[artist_codes] = norm_counts.astype(np.float32, copy=False)

    def get_track_index(self, track_id: str) -> int | None:
        if self.track_ids_sorted is None or self.track_row_indices_sorted is None:
            return None

        key = track_id.encode('utf-8')
        pos = int(np.searchsorted(self.track_ids_sorted, key, side='left'))
        if pos >= len(self.track_ids_sorted) or self.track_ids_sorted[pos] != key:
            return None
        return int(self.track_row_indices_sorted[pos])

    def get_track_id(self, row_idx: int) -> str:
        if self.track_ids_sorted is None or self.track_sorted_pos_by_row is None:
            raise KeyError(f"Track row {row_idx} is unavailable")
        sorted_pos = int(self.track_sorted_pos_by_row[row_idx])
        return self.track_ids_sorted[sorted_pos].decode('utf-8')

    def get_artist_code(self, artist_name: str) -> int | None:
        return self.artist_name_to_code.get(artist_name)

    def get_artist_name(self, artist_code: int) -> str:
        return self.artist_names_by_code[artist_code]

    def get_artist_genre_profiles(self, artist_names: list[str]) -> dict[str, list[tuple[str, float]]]:
        if self.df is None or 'genre' not in self.df.columns:
            return {artist: [] for artist in artist_names}

        ordered_artists = [artist for artist in dict.fromkeys(artist_names) if artist]
        missing = [artist for artist in ordered_artists if artist not in self.genre_profile_cache]

        if missing:
            artist_codes = [
                code
                for artist in missing
                if (code := self.get_artist_code(artist)) is not None
            ]

            if artist_codes:
                genre_df = self.df.filter(
                    pl.col('artist_code').is_in(artist_codes)
                    & pl.col('genre').is_not_null()
                )
                if not genre_df.is_empty():
                    counts = (
                        genre_df.group_by(['artist_code', 'genre'])
                        .agg(pl.len().alias('count'))
                    )
                    totals = (
                        counts.group_by('artist_code')
                        .agg(pl.col('count').sum().alias('total'))
                    )
                    enriched = (
                        counts.join(totals, on='artist_code', how='left')
                        .with_columns((pl.col('count') * 100.0 / pl.col('total')).round(1).alias('pct'))
                        .filter(pl.col('pct') > 1.0)
                        .sort(['artist_code', 'pct'], descending=[False, True])
                    )

                    for artist in missing:
                        self.genre_profile_cache.setdefault(artist, [])

                    for row in enriched.iter_rows(named=True):
                        artist = self.get_artist_name(int(row['artist_code']))
                        bucket = self.genre_profile_cache.setdefault(artist, [])
                        if len(bucket) < 3:
                            bucket.append((row['genre'], float(row['pct'])))
                else:
                    for artist in missing:
                        self.genre_profile_cache.setdefault(artist, [])
            else:
                for artist in missing:
                    self.genre_profile_cache.setdefault(artist, [])

            if len(self.genre_profile_cache) > 10_000:
                # Debug-only cache: keep only the artists from the current request.
                self.genre_profile_cache = {
                    artist: self.genre_profile_cache.get(artist, [])
                    for artist in ordered_artists
                }

        return {artist: self.genre_profile_cache.get(artist, []) for artist in ordered_artists}
    



def squared_euclidean_distance(
    query: np.ndarray, 
    matrix: np.ndarray, 
    matrix_norms_sq: np.ndarray | None = None
) -> np.ndarray:
    """Compute squared Euclidean distance using dot-product form (avoids large temp allocation).
    
    ||x - q||² = ||x||² + ||q||² - 2x·q
    """
    query = query.astype(np.float32).flatten()
    query_norm_sq = np.dot(query, query)
    
    if matrix_norms_sq is None:
        matrix_norms_sq = np.sum(matrix.astype(np.float32) ** 2, axis=1)
    
    dot_products = np.dot(matrix.astype(np.float32), query)
    
    return matrix_norms_sq + query_norm_sq - 2.0 * dot_products


def cosine_distance(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    query_norm = np.linalg.norm(query)
    if query_norm == 0:
        return np.ones(len(matrix), dtype=matrix.dtype)
    
    matrix_norms = np.linalg.norm(matrix, axis=1)
    dot_products = np.dot(matrix, query.flatten())
    
    with np.errstate(divide='ignore', invalid='ignore'):
        cosine_sim = dot_products / (matrix_norms * query_norm)
        cosine_sim = np.nan_to_num(cosine_sim, nan=0.0)
    
    return 1.0 - cosine_sim


# Weights for seed types
WEIGHT_USER_SELECTED_TOTAL = 8.0  # Total weight budget for user-selected tracks per artist
WEIGHT_USER_SELECTED_MIN = 2.0    # Minimum weight per user track (prevents dilution)
WEIGHT_AUTO_SAMPLED_TOTAL = 6.0   # Total weight budget for auto-sampled tracks per artist
MAX_DIVERSE_SEEDS_PER_ARTIST_BASE = 16  # Max diverse tracks when single artist

# Hierarchical soft-min tau values
TAU_WITHIN_ARTIST = 0.3  # Low = close to ANY track from artist counts
TAU_BETWEEN_ARTISTS = 1.5  # High = must be close to ALL artists (intersection)


def get_max_seeds_per_artist(num_artists: int) -> int:
    """Scale max seeds inversely with artist count to balance representation."""
    return max(6, MAX_DIVERSE_SEEDS_PER_ARTIST_BASE // num_artists)


def select_diverse_tracks(vectors: np.ndarray, k: int) -> list[int]:
    """Select k diverse tracks using density-aware greedy selection.
    
    Uses inverse average distance as density proxy:
    - Tracks in crowded regions (low avg distance) get boosted
    - Isolated outliers (high avg distance) get dampened
    - Result: diverse selection proportional to catalog density
    
    If len(vectors) <= k, returns all indices.
    """
    n = len(vectors)
    if n <= k:
        return list(range(n))
    
    vectors = vectors.astype(np.float32)
    
    # Precompute pairwise distances and density (avg dist to others)
    dists_matrix = np.linalg.norm(vectors[:, None] - vectors[None, :], axis=2)
    np.fill_diagonal(dists_matrix, 0)
    avg_dists = np.mean(dists_matrix, axis=1)
    avg_dists = np.maximum(avg_dists, 1e-6)  # Avoid division by zero
    
    selected = [0]
    min_dists = dists_matrix[0].copy()
    min_dists[0] = -np.inf
    
    for _ in range(k - 1):
        # Score = min_distance / avg_distance (density-adjusted)
        scores = min_dists / avg_dists
        next_idx = int(np.argmax(scores))
        selected.append(next_idx)
        
        # Update min distances using precomputed matrix
        min_dists = np.minimum(min_dists, dists_matrix[next_idx])
        min_dists[next_idx] = -np.inf
    
    return selected


def get_seed_indices_grouped(
    data: MusicData,
    artists: list[str],
    track_ids: list[str] | None = None,
) -> dict[int, list[tuple[int, float]]]:
    """Get seed track indices grouped by artist for hierarchical aggregation.
    
    Returns dict mapping artist_code -> list of (track_idx, weight) tuples.
    User-selected tracks get distributed weight, then auto-sampled tracks fill remaining slots.
    """
    df = data.df
    matrix_audio = data.matrix_audio

    artist_seeds: dict[int, list[tuple[int, float]]] = {}
    artist_user_indices: dict[int, list[int]] = {}
    
    num_artists = len(artists) if artists else 1
    max_seeds = get_max_seeds_per_artist(num_artists)
    
    # Phase 1: Collect user-selected tracks per artist
    if track_ids:
        for tid in track_ids:
            idx = data.get_track_index(tid)
            if idx is None:
                continue
            artist_code = int(data.track_artist_codes[idx])
            artist_user_indices.setdefault(artist_code, []).append(idx)
    
    # Phase 2: Distribute weight across user tracks and add to seeds
    for artist_code, user_indices in artist_user_indices.items():
        n_user = len(user_indices)
        weight_per_track = max(WEIGHT_USER_SELECTED_MIN, WEIGHT_USER_SELECTED_TOTAL / n_user)
        artist_seeds[artist_code] = [(idx, weight_per_track) for idx in user_indices]
    
    # Phase 3: For each artist, auto-sample diverse tracks to fill remaining slots
    all_artists = {
        code
        for artist in artists
        if (code := data.get_artist_code(artist)) is not None
    }
    all_artists.update(artist_user_indices.keys())
    
    for artist_code in all_artists:
        existing_indices = {idx for idx, _ in artist_seeds.get(artist_code, [])}
        slots_remaining = max_seeds - len(existing_indices)
        
        if slots_remaining <= 0:
            continue
        
        artist_df = df.filter(pl.col("artist_code") == artist_code)
        if len(artist_df) == 0:
            continue
        
        # Take top tracks by popularity as candidates, then select diverse subset
        n_candidates = max_seeds * DIVERSITY_CANDIDATE_MULTIPLIER
        if 'popularity' in artist_df.columns:
            top_df = artist_df.sort('popularity', descending=True).head(n_candidates)
        else:
            top_df = artist_df.head(n_candidates)
        
        candidate_indices = [
            int(row_idx)
            for row_idx in top_df['row_idx'].to_list()
            if int(row_idx) not in existing_indices
        ]
        
        if candidate_indices:
            candidate_vectors = matrix_audio[candidate_indices]
            diverse_local = select_diverse_tracks(candidate_vectors, k=slots_remaining)
            
            if artist_code not in artist_seeds:
                artist_seeds[artist_code] = []
            
            # Distribute auto-sampled weight budget across selected tracks
            n_auto = len(diverse_local)
            weight_per_auto = WEIGHT_AUTO_SAMPLED_TOTAL / n_auto if n_auto > 0 else 1.0
            artist_seeds[artist_code].extend([
                (candidate_indices[local_idx], weight_per_auto)
                for local_idx in diverse_local
            ])
    
    # Boost all seeds for artists with small catalogs so they're not underrepresented
    for artist_code, seeds in artist_seeds.items():
        n_seeds = len(seeds)
        if n_seeds < max_seeds:
            weight_boost = max_seeds / n_seeds
            artist_seeds[artist_code] = [(idx, w * weight_boost) for idx, w in seeds]
    
    return artist_seeds


def soft_min_distance(
    d_stack: np.ndarray,
    weights: np.ndarray,
    tau: float
) -> np.ndarray:
    """Aggregate distances using weighted soft-min.
    
    Formula: soft_min(d) = -τ * log(Σ wᵢ * exp(-dᵢ / τ) / Σ wᵢ)
    
    Args:
        d_stack: (K, N) array of distances
        weights: (K,) array of weights
        tau: Temperature
    """
    if len(d_stack) == 1:
        return d_stack[0]
    
    w = weights.reshape(-1, 1).astype(np.float32)
    scaled = -d_stack / tau
    max_scaled = np.max(scaled, axis=0, keepdims=True)
    
    weighted_exp = w * np.exp(scaled - max_scaled)
    log_weighted_sum = max_scaled.squeeze() + np.log(np.sum(weighted_exp, axis=0) + 1e-12)
    log_weighted_sum -= np.log(np.sum(w) + 1e-12)
    
    return -tau * log_weighted_sum


def hierarchical_soft_min_distance(
    d_total_stack: np.ndarray,
    artist_ranges: list[tuple[int, int, int]],
    weights: np.ndarray,
    tau_within: float = TAU_WITHIN_ARTIST,
    tau_between: float = TAU_BETWEEN_ARTISTS
) -> np.ndarray:
    """Two-stage soft-min: low tau within artist, high tau between artists.
    
    Stage 1: For each artist, soft-min with low tau (close to ANY track counts)
    Stage 2: Across artists, soft-min with high tau (must be close to ALL)
    """
    if len(artist_ranges) == 1:
        name, start, end = artist_ranges[0]
        return soft_min_distance(d_total_stack[start:end], weights[start:end], tau_within)
    
    per_artist_distances = []
    per_artist_weights = []
    
    for name, start, end in artist_ranges:
        artist_d = soft_min_distance(d_total_stack[start:end], weights[start:end], tau_within)
        per_artist_distances.append(artist_d)
        per_artist_weights.append(np.sum(weights[start:end]))
    
    d_artists = np.stack(per_artist_distances, axis=0).astype(np.float32)
    w_artists = np.array(per_artist_weights, dtype=np.float32)
    
    return soft_min_distance(d_artists, w_artists, tau_between)


def generate_recommendations(
    data: MusicData,
    input_artists: list[str],
    track_ids: list[str] | None = None,
    exclude_artists: list[str] | None = None,
    diversity: int = VARIETY,
    max_artists: int = MAX_ARTISTS,
    genre_weight: int = GENRE_FOCUS,
    tracks_per_artist: int = TRACKS_PER_ARTIST,
    vibe_modifiers: dict[str, float] | None = None,  # e.g., {'mood': 0.5, 'sound': -0.3}
    popularity: float = 0.0,  # -1 (hidden gems) to +1 (mainstream)
    debug: bool = False,
    debug_audio: bool = False,
) -> tuple[dict[str, list[dict]], dict]:
    t_start = perf_counter()
    df = data.df
    matrix_audio = data.matrix_audio
    matrix_genre = data.matrix_genre
    if df is None or matrix_audio is None or matrix_genre is None:
        return {}, {"has_more_candidates": False}
    
    grouped_seeds = get_seed_indices_grouped(data, input_artists, track_ids)
    t_seeds = perf_counter()
    
    if not grouped_seeds:
        return {}, {"has_more_candidates": False}
    
    # Flatten grouped seeds while tracking artist ranges for hierarchical aggregation
    seed_indices: list[int] = []
    weights: list[float] = []
    artist_ranges: list[tuple[int, int, int]] = []
    
    for artist_code, seeds in grouped_seeds.items():
        start = len(seed_indices)
        for idx, w in seeds:
            seed_indices.append(idx)
            weights.append(w)
        end = len(seed_indices)
        artist_ranges.append((artist_code, start, end))

    seed_index_arr = np.asarray(seed_indices, dtype=np.int32)
    seeds_audio_stack = matrix_audio[seed_index_arr].astype(np.float32, copy=True)
    seeds_genre_stack = matrix_genre[seed_index_arr].astype(np.float32)
    seeds_genre_norms = np.linalg.norm(seeds_genre_stack, axis=1, keepdims=True)
    seeds_genre_norms[seeds_genre_norms == 0] = 1.0
    seeds_genre_stack = seeds_genre_stack / seeds_genre_norms
    
    if vibe_modifiers:
        for vibe_name, slider_value in vibe_modifiers.items():
            if vibe_name not in VIBE_DIMENSIONS or slider_value == 0:
                continue
            for feature, weight in VIBE_DIMENSIONS[vibe_name].items():
                feature_idx = data.audio_col_indices.get(feature)
                if feature_idx is None:
                    continue
                offset = slider_value * weight * VIBE_SLIDER_STRENGTH * FEATURE_WEIGHTS[feature]
                seeds_audio_stack[:, feature_idx] += offset
    
    t_prep = perf_counter()
    # Audio-only candidate generation: fast 12D matmul to find candidates before rerank,
    fetch_k = min(SAMPLE_SIZE * ANN_OVERFETCH, len(matrix_audio))
    
    # Reduce audio candidates in small seed batches so we never allocate a
    # full (num_seeds x num_tracks) distance matrix. The previous approach could
    # spike request-time RSS by hundreds of MB on large seed sets.
    d_audio_sq_min: np.ndarray | None = None
    for start in range(0, len(seeds_audio_stack), AUDIO_CANDIDATE_BATCH_SEEDS):
        batch = seeds_audio_stack[start:start + AUDIO_CANDIDATE_BATCH_SEEDS]
        batch_norms_sq = np.sum(batch ** 2, axis=1, keepdims=True)
        batch_dots = batch @ matrix_audio.T
        batch_d_audio_sq = data.audio_norms_sq + batch_norms_sq - 2.0 * batch_dots
        batch_min = np.min(batch_d_audio_sq, axis=0)
        if d_audio_sq_min is None:
            d_audio_sq_min = batch_min
        else:
            np.minimum(d_audio_sq_min, batch_min, out=d_audio_sq_min)

    if fetch_k >= len(matrix_audio):
        candidates = np.arange(len(matrix_audio), dtype=np.int32)
    else:
        top_k_idx = np.argpartition(d_audio_sq_min, fetch_k)[:fetch_k]
        candidates = np.sort(top_k_idx)
    
    # Recompute per-seed audio distances only on the final candidate subset.
    candidate_audio = matrix_audio[candidates]
    candidate_audio_norms_sq = data.audio_norms_sq[candidates]
    seeds_norm_sq = np.sum(seeds_audio_stack ** 2, axis=1, keepdims=True)
    dot_products_cand = seeds_audio_stack @ candidate_audio.T
    d_audio = np.sqrt(np.maximum(candidate_audio_norms_sq + seeds_norm_sq - 2.0 * dot_products_cand, 0))
    del d_audio_sq_min, dot_products_cand
    
    t_audio = perf_counter()
    # Genre distance (cosine) computed ONLY on candidate subset (upcast from f16)
    cand_genre = matrix_genre[candidates].astype(np.float32)
    cand_genre_norms = data.genre_norms[candidates]
    genre_dots = seeds_genre_stack @ cand_genre.T
    with np.errstate(divide='ignore', invalid='ignore'):
        cosine_sim = genre_dots / (seeds_genre_norms * cand_genre_norms)
        cosine_sim = np.nan_to_num(cosine_sim, nan=0.0, posinf=0.0, neginf=0.0)
    d_genre = 1.0 - cosine_sim
    
    t_genre = perf_counter()
    # Look up effective weight from curve (0=None, 1=Low, 2=Medium, 3=High, 4=Max)
    effective_genre_weight = GENRE_WEIGHT_CURVE[genre_weight]
    
    # Combined distance per seed
    d_total_stack = np.sqrt(d_audio**2 + (d_genre * effective_genre_weight)**2)
    
    # Hierarchical aggregation: low tau within artists, high tau between
    weights_arr = np.array(weights, dtype=np.float32)
    d_total = hierarchical_soft_min_distance(d_total_stack, artist_ranges, weights_arr)
    
    # Apply popularity and track count as distance adjustments
    if popularity != 0 and data.artist_popularity_by_code is not None:
        pop_weight = 0.6
        track_weight = 0.2
        candidate_artist_codes = data.track_artist_codes[candidates].astype(np.int32, copy=False)
        pop_adjustment = (data.artist_popularity_by_code[candidate_artist_codes] - data.popularity_median) * popularity * pop_weight
        track_adjustment = (data.artist_track_count_by_code[candidate_artist_codes] - 0.5) * popularity * track_weight
        d_total = d_total - pop_adjustment - track_adjustment
    
    # Use Gumbel noise for variety on the candidate set
    n = min(SAMPLE_SIZE, len(d_total))
    k = n - 1
    if diversity > 0:
        noise_scale = VARIETY_NOISE_SCALE * diversity
        noise = np.random.gumbel(loc=0.0, scale=noise_scale, size=d_total.shape).astype(np.float32)
        d_noisy = d_total.astype(np.float32) + noise
        top_n_unsorted = np.argpartition(d_noisy, k)[:n]
        top_n_sorted = top_n_unsorted[np.argsort(d_noisy[top_n_unsorted])]
    else:
        top_n_unsorted = np.argpartition(d_total, k)[:n]
        top_n_sorted = top_n_unsorted[np.argsort(d_total[top_n_unsorted])]
    
    t_rank = perf_counter()
    # Map back from candidate-local indices to global track indices
    similar_indices = candidates[top_n_sorted]
    
    # Get similar songs and add score (higher = better, based on position in sorted list)
    similar_df = df[similar_indices.tolist()]
    #scores = np.arange(n, 0, -1)

    # Zipfian scoring: rewards top matches significantly more than lower ones
    # Score = 1000 / (Rank + K)
    # scores = 1000.0 / (np.arange(1, n + 1) + 25.0)

    smoothing_factor = SAMPLE_SIZE * 0.025
    scores = 1000.0 / (np.arange(1, n + 1) + smoothing_factor)

    similar_df = similar_df.with_columns(pl.Series("score", scores))
    
    # Exclude input artists and any explicitly excluded artists
    excluded_codes = {
        code
        for artist in input_artists
        if (code := data.get_artist_code(artist)) is not None
    }
    if exclude_artists:
        excluded_codes.update(
            code
            for artist in exclude_artists
            if (code := data.get_artist_code(artist)) is not None
        )
    pool = similar_df.filter(~pl.col('artist_code').is_in(list(excluded_codes)))
    
    # Group and aggregate - fetch one extra to detect if more candidates exist
    artist_stats_full = (
        pool.group_by('artist_code')
        .agg([
            # Get scores of top K tracks for this artist
            pl.col('score').sort(descending=True).head(tracks_per_artist).sum().alias('total_score'),
            pl.col('row_idx').count().alias('track_count')
        ])
        .filter(pl.col('track_count') >= 2)
        .sort('total_score', descending=True)
        .head(max_artists + 1)
    )
    
    has_more_candidates = len(artist_stats_full) > max_artists
    
    artist_stats = (
        artist_stats_full.head(max_artists)
        .with_columns(
            pl.col('track_count').clip(upper_bound=tracks_per_artist).alias('display_count')
        )
        .sort(['display_count', 'total_score'], descending=[True, True])
    )

    artist_profiles = (
        data.get_artist_genre_profiles(
            input_artists + [data.get_artist_name(int(code)) for code in artist_stats['artist_code'].to_list()]
        )
        if debug else {}
    )
    
    recommendations = {}
    debug_info = {} if debug else None
    
    for row in artist_stats.iter_rows(named=True):
        artist_code = int(row['artist_code'])
        artist = data.get_artist_name(artist_code)
        artist_tracks = (
            pool.filter(pl.col('artist_code') == artist_code)
            .sort('score', descending=True)
            .head(tracks_per_artist)
        )
        
        # Build tracks with optional per-song debug data
        tracks = []
        for r in artist_tracks.iter_rows(named=True):
            track_idx = int(r['row_idx'])
            track_info = {
                "track_id": data.get_track_id(track_idx),
                "track_name": r['track_name'],
                "genre": r.get('genre')
            }
            
            # Add per-song debug data if requested
            if debug and debug_audio:
                # Extract audio features for this specific song
                key_features = ['energy', 'danceability', 'acousticness', 'valence', 'tempo', 'instrumentalness']
                features_to_use = [c for c in key_features if c in data.audio_cols]
                
                audio_feats = {}
                for feat in features_to_use:
                    idx = data.audio_col_indices[feat]
                    # Divide by weight to get original value
                    raw_val = float(matrix_audio[track_idx, idx]) / FEATURE_WEIGHTS[feat]
                    audio_feats[feat] = round(raw_val, 3)
                
                # Include track's actual genre
                if r.get('genre'):
                    audio_feats['genre'] = r['genre']
                
                if audio_feats:  # Only add if we have features
                    track_info['audio_features'] = audio_feats
            
            tracks.append(track_info)
        
        recommendations[artist] = tracks
        
        # Build debug info for this artist (genre profile only)
        if debug:
            artist_debug = {}
            genre_profile = artist_profiles.get(artist, [])
            artist_debug['genre_profile'] = [
                {"genre": g, "pct": p} for g, p in genre_profile
            ]
            debug_info[artist] = artist_debug
    
    t_postprocess = perf_counter()
    print(f"[perf] seeds={1000*(t_seeds-t_start):.0f}ms prep={1000*(t_prep-t_seeds):.0f}ms "
          f"audio={1000*(t_audio-t_prep):.0f}ms genre={1000*(t_genre-t_audio):.0f}ms "
          f"rank={1000*(t_rank-t_genre):.0f}ms post={1000*(t_postprocess-t_rank):.0f}ms "
          f"TOTAL={1000*(t_postprocess-t_start):.0f}ms candidates={len(candidates)}")
    meta = {
        "has_more_candidates": has_more_candidates,
    }
    if debug:
        meta["debug"] = debug_info
        # Include input artists genre profile for comparison
        input_profile = []
        for inp_artist in input_artists:
            profile = artist_profiles.get(inp_artist, [])
            if profile:
                input_profile.append({
                    "artist": inp_artist,
                    "genres": [{"genre": g, "pct": p} for g, p in profile]
                })
        meta["input_genre_profile"] = input_profile
        
        # Include search vector audio features if requested (average of seeds for display)
        if debug_audio and len(seed_indices) > 0:
            key_features = ['energy', 'danceability', 'acousticness', 'valence', 'tempo', 'instrumentalness']
            features_to_use = [c for c in key_features if c in data.audio_cols]
            
            # Average seeds for debug display (actual search uses soft-min)
            avg_seed = np.mean(seeds_audio_stack, axis=0)
            
            search_audio = {}
            for feat in features_to_use:
                idx = data.audio_col_indices[feat]
                raw_val = float(avg_seed[idx]) / FEATURE_WEIGHTS[feat]
                clamped_val = max(0.0, min(1.0, raw_val))
                search_audio[feat] = round(clamped_val, 3)
            
            meta["search_vector_audio"] = search_audio
            meta["num_seeds"] = len(seed_indices)  # Show how many seeds are being used
        
        # Include search vector genre profile using actual text genres
        if debug_audio and 'genre' in df.columns:
            # Build genre profile from input artists' tracks
            input_artist_codes = [
                code
                for artist in input_artists
                if (code := data.get_artist_code(artist)) is not None
            ]
            input_artist_df = df.filter(pl.col('artist_code').is_in(input_artist_codes))
            if len(input_artist_df) > 0:
                # Count actual text genres from input artists
                genre_counts = {}
                for genre in input_artist_df.filter(pl.col('genre').is_not_null())['genre'].to_list():
                    if genre:
                        genre_counts[genre] = genre_counts.get(genre, 0) + 1
                
                if genre_counts:
                    total = sum(genre_counts.values())
                    genre_pcts = []
                    for genre, count in genre_counts.items():
                        pct = (count / total) * 100
                        if pct > 1:  # Only include genres with >1%
                            genre_pcts.append((genre, round(pct, 1)))
                    
                    # Sort by percentage and keep top genres
                    genre_pcts.sort(key=lambda x: x[1], reverse=True)
                    genre_profile = [{"genre": g, "pct": p} for g, p in genre_pcts[:8]]
                    meta["search_vector_genre"] = genre_profile
    
    return recommendations, meta
