"""
Recommendation logic for Vibe music recommendation app.
Updated to use polars instead of pandas for memory efficiency.
"""
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


class DataSource(Protocol):
    def load(self) -> pl.DataFrame:
        ...


class ParquetDataSource:
    def __init__(self, path: Path):
        self.path = path
    
    def load(self) -> pl.DataFrame:
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
        self.audio_cols: list[str] = []
        self.genre_cols: list[str] = []
        self.track_id_to_idx: dict[str, int] = {}
        self.track_id_to_artist: dict[str, str] = {}  # For multi-song balancing
        self.artist_popularity: np.ndarray | None = None  # Per-track artist popularity (0-1)
        self.artist_track_count: np.ndarray | None = None  # Per-track log-normalized track count (0-1)
        self.popularity_median: float = 0.5  # Median artist popularity for centering
        # Debug info cache 
        self.artist_genre_profile: dict[str, list[tuple[str, float]]] = {}
    
    def load(self) -> None:
        t0 = perf_counter()
        print("[startup] Loading encoded parquet...")
        df = self.source.load()
        print(f"[startup] Loaded parquet rows: {len(df):,}")
        
        required = ['artist_name', 'track_name', 'track_id']
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Filter out rows with null required fields (data quality safeguard)
        for col in required:
            null_count = df[col].null_count()
            if null_count > 0:
                print(f"Warning: Filtering {null_count} rows with null {col}")
                df = df.filter(pl.col(col).is_not_null())
        
        self.genre_cols = [c for c in df.columns if c.startswith('genre_')]
        self.audio_cols = [c for c in FEATURE_WEIGHTS.keys() if c in df.columns]
        print(f"[startup] Building audio matrix ({len(self.audio_cols)} cols)...")
        
        # Audio Matrix (Weighted for Euclidean)
        audio_data = df.select(self.audio_cols).to_numpy().astype(np.float32)
        weights = np.array([FEATURE_WEIGHTS[c] for c in self.audio_cols], dtype=np.float32)
        self.matrix_audio = audio_data * weights
        
        # Precompute squared norms for fast Euclidean distance: ||x-q||² = ||x||² + ||q||² - 2x·q
        self.audio_norms_sq = np.sum(self.matrix_audio ** 2, axis=1)
        
        # Genre Matrix (Unweighted for Cosine)
        self.matrix_genre = df.select(self.genre_cols).to_numpy().astype(np.float32)
        
        # Precompute genre norms once (avoid recomputation per request)
        self.genre_norms = np.linalg.norm(self.matrix_genre, axis=1)
        self.genre_norms[self.genre_norms == 0] = 1.0  # Prevent division by zero
        print(f"[startup] Matrices ready (audio + genre)")
        
        # Sort artists by popularity
        artist_popularity = (
            df.group_by('artist_name')
            .agg(pl.col('popularity').sum())
            .sort('popularity', descending=True)
        )
        self.artists_list = artist_popularity['artist_name'].to_list()
        print(f"[startup] Indexed {len(self.artists_list):,} artists by popularity")
        
        # Build track_id lookups for O(1) access
        track_ids = df['track_id'].to_list()
        artist_names = df['artist_name'].to_list()
        self.track_id_to_idx = {tid: i for i, tid in enumerate(track_ids)}
        self.track_id_to_artist = {tid: artist for tid, artist in zip(track_ids, artist_names)}
        print(f"[startup] Built track lookup maps ({len(self.track_id_to_idx):,} track_ids)")
        
        # Precompute artist-level popularity (avg track popularity per artist)
        self._build_artist_popularity(df)
        
        # Cache per-artist genre profiles (top 3 genres with percentages)
        self._build_genre_profiles(df)
        
        # Keep metadata for display/lookup
        keep_cols = ['artist_name', 'track_name', 'track_id']
        for col in ['popularity', 'genre']:
            if col in df.columns:
                keep_cols.append(col)
        
        self.df = df.select(keep_cols)
        elapsed = perf_counter() - t0
        print(f"[startup] MusicData load complete in {elapsed:.2f}s")
    
    def _build_artist_popularity(self, df: pl.DataFrame) -> None:
        """Build per-track artist popularity and track count arrays for popularity slider."""
        # Compute mean popularity and track count per artist
        artist_stats = (
            df.group_by('artist_name')
            .agg([
                pl.col('popularity').cast(pl.Float32).mean().alias('avg_pop'),
                pl.len().alias('track_count')
            ])
        )
        artist_names = artist_stats['artist_name'].to_list()
        avg_pops = artist_stats['avg_pop'].to_list()
        track_counts = np.array(artist_stats['track_count'].to_list(), dtype=np.float32)
        
        # Log-normalize track counts to 0-1 range
        log_counts = np.log1p(track_counts)
        max_log = log_counts.max()
        norm_counts = log_counts / max_log if max_log > 0 else log_counts
        
        artist_pop_dict = dict(zip(artist_names, avg_pops))
        artist_count_dict = dict(zip(artist_names, norm_counts))
        
        # Store median for centering
        self.popularity_median = float(np.median(avg_pops))
        
        # Create per-track arrays
        track_artist_names = df['artist_name'].to_list()
        self.artist_popularity = np.array(
            [artist_pop_dict.get(a, self.popularity_median) for a in track_artist_names],
            dtype=np.float32
        )
        self.artist_track_count = np.array(
            [artist_count_dict.get(a, 0.5) for a in track_artist_names],
            dtype=np.float32
        )
    
    def _build_genre_profiles(self, df: pl.DataFrame) -> None:
        """Build per-artist genre distribution from actual track genres (not encoded vectors)."""
        if 'genre' not in df.columns:
            return

        genre_df = df.filter(pl.col('genre').is_not_null())
        if genre_df.is_empty():
            return

        counts = (
            genre_df.group_by(['artist_name', 'genre'])
            .agg(pl.len().alias('count'))
        )
        totals = (
            counts.group_by('artist_name')
            .agg(pl.col('count').sum().alias('total'))
        )
        enriched = (
            counts.join(totals, on='artist_name', how='left')
            .with_columns((pl.col('count') * 100.0 / pl.col('total')).round(1).alias('pct'))
            .filter(pl.col('pct') > 1.0)
            .sort(['artist_name', 'pct'], descending=[False, True])
        )

        self.artist_genre_profile.clear()
        for row in enriched.iter_rows(named=True):
            artist = row['artist_name']
            item = (row['genre'], float(row['pct']))
            bucket = self.artist_genre_profile.setdefault(artist, [])
            if len(bucket) < 3:
                bucket.append(item)
    



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
    df: pl.DataFrame,
    matrix_audio: np.ndarray,
    artists: list[str],
    track_id_to_idx: dict[str, int],
    track_ids: list[str] | None = None,
    track_id_to_artist: dict[str, str] | None = None
) -> dict[str, list[tuple[int, float]]]:
    """Get seed track indices grouped by artist for hierarchical aggregation.
    
    Returns dict mapping artist -> list of (track_idx, weight) tuples.
    User-selected tracks get distributed weight, then auto-sampled tracks fill remaining slots.
    """
    artist_seeds: dict[str, list[tuple[int, float]]] = {}
    artist_user_indices: dict[str, list[int]] = {}
    
    num_artists = len(artists) if artists else 1
    max_seeds = get_max_seeds_per_artist(num_artists)
    
    # Phase 1: Collect user-selected tracks per artist
    if track_ids and track_id_to_artist:
        for tid in track_ids:
            if tid in track_id_to_idx:
                artist = track_id_to_artist.get(tid, "_unknown")
                idx = track_id_to_idx[tid]
                if artist not in artist_user_indices:
                    artist_user_indices[artist] = []
                artist_user_indices[artist].append(idx)
    elif track_ids:
        for tid in track_ids:
            if tid in track_id_to_idx:
                if "_unknown" not in artist_user_indices:
                    artist_user_indices["_unknown"] = []
                artist_user_indices["_unknown"].append(track_id_to_idx[tid])
    
    # Phase 2: Distribute weight across user tracks and add to seeds
    for artist, user_indices in artist_user_indices.items():
        n_user = len(user_indices)
        weight_per_track = max(WEIGHT_USER_SELECTED_MIN, WEIGHT_USER_SELECTED_TOTAL / n_user)
        artist_seeds[artist] = [(idx, weight_per_track) for idx in user_indices]
    
    # Phase 3: For each artist, auto-sample diverse tracks to fill remaining slots
    all_artists = set(artists) if artists else set()
    all_artists.update(artist_user_indices.keys())
    
    for artist in all_artists:
        if artist == "_unknown":
            continue
            
        existing_indices = {idx for idx, _ in artist_seeds.get(artist, [])}
        slots_remaining = max_seeds - len(existing_indices)
        
        if slots_remaining <= 0:
            continue
        
        artist_df = df.filter(pl.col("artist_name") == artist)
        if len(artist_df) == 0:
            continue
        
        # Take top tracks by popularity as candidates, then select diverse subset
        n_candidates = max_seeds * DIVERSITY_CANDIDATE_MULTIPLIER
        top_df = artist_df.sort('popularity', descending=True).head(n_candidates)
        
        candidate_indices = [
            track_id_to_idx[tid]
            for tid in top_df['track_id'].to_list()
            if tid in track_id_to_idx and track_id_to_idx[tid] not in existing_indices
        ]
        
        if candidate_indices:
            candidate_vectors = matrix_audio[candidate_indices]
            diverse_local = select_diverse_tracks(candidate_vectors, k=slots_remaining)
            
            if artist not in artist_seeds:
                artist_seeds[artist] = []
            
            # Distribute auto-sampled weight budget across selected tracks
            n_auto = len(diverse_local)
            weight_per_auto = WEIGHT_AUTO_SAMPLED_TOTAL / n_auto if n_auto > 0 else 1.0
            artist_seeds[artist].extend([
                (candidate_indices[local_idx], weight_per_auto)
                for local_idx in diverse_local
            ])
    
    # Boost all seeds for artists with small catalogs so they're not underrepresented
    for artist, seeds in artist_seeds.items():
        if artist == "_unknown":
            continue
        n_seeds = len(seeds)
        if n_seeds < max_seeds:
            weight_boost = max_seeds / n_seeds
            artist_seeds[artist] = [(idx, w * weight_boost) for idx, w in seeds]
    
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
    artist_ranges: list[tuple[str, int, int]],
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
    df = data.df
    matrix_audio = data.matrix_audio
    matrix_genre = data.matrix_genre
    lookup = data.track_id_to_idx
    artist_lookup = data.track_id_to_artist
    
    grouped_seeds = get_seed_indices_grouped(df, matrix_audio, input_artists, lookup, track_ids, artist_lookup)
    
    if not grouped_seeds:
        return {}, {"has_more_candidates": False}
    
    # Flatten grouped seeds while tracking artist ranges for hierarchical aggregation
    seed_indices: list[int] = []
    weights: list[float] = []
    artist_ranges: list[tuple[str, int, int]] = []
    
    for artist, seeds in grouped_seeds.items():
        start = len(seed_indices)
        for idx, w in seeds:
            seed_indices.append(idx)
            weights.append(w)
        end = len(seed_indices)
        artist_ranges.append((artist, start, end))
    
    seeds_audio = [matrix_audio[idx] for idx in seed_indices]
    seeds_genre_raw = [matrix_genre[idx] for idx in seed_indices]
    seeds_genre = [
        s / np.linalg.norm(s) if np.linalg.norm(s) > 0 else s
        for s in seeds_genre_raw
    ]
    
    if vibe_modifiers:
        modified_seeds = []
        for seed in seeds_audio:
            seed = seed.copy().astype(np.float32)
            for vibe_name, slider_value in vibe_modifiers.items():
                if vibe_name in VIBE_DIMENSIONS and slider_value != 0:
                    for feature, weight in VIBE_DIMENSIONS[vibe_name].items():
                        if feature in data.audio_cols:
                            idx = data.audio_cols.index(feature)
                            offset = slider_value * weight * VIBE_SLIDER_STRENGTH * FEATURE_WEIGHTS[feature]
                            seed[idx] += offset
            modified_seeds.append(seed)
        seeds_audio = modified_seeds
    
    seeds_audio_stack = np.stack(seeds_audio, axis=0).astype(np.float32)
    seeds_genre_stack = np.stack(seeds_genre, axis=0).astype(np.float32)
    
    # Batch audio distance
    seeds_norm_sq = np.sum(seeds_audio_stack ** 2, axis=1, keepdims=True)
    dot_products = seeds_audio_stack @ matrix_audio.T
    d_audio_sq = data.audio_norms_sq + seeds_norm_sq - 2.0 * dot_products
    d_audio = np.sqrt(np.maximum(d_audio_sq, 0))
    
    # Batch genre distance (cosine) - use precomputed norms
    seeds_genre_norms = np.linalg.norm(seeds_genre_stack, axis=1, keepdims=True)
    genre_dots = seeds_genre_stack @ matrix_genre.T
    with np.errstate(divide='ignore', invalid='ignore'):
        cosine_sim = genre_dots / (seeds_genre_norms * data.genre_norms)
        cosine_sim = np.nan_to_num(cosine_sim, nan=0.0, posinf=0.0, neginf=0.0)
    d_genre = 1.0 - cosine_sim
    
    # Look up effective weight from curve (0=None, 1=Low, 2=Medium, 3=High, 4=Max)
    effective_genre_weight = GENRE_WEIGHT_CURVE[genre_weight]
    
    # Combined distance per seed
    d_total_stack = np.sqrt(d_audio**2 + (d_genre * effective_genre_weight)**2)
    
    # Hierarchical aggregation: low tau within artists, high tau between
    weights_arr = np.array(weights, dtype=np.float32)
    d_total = hierarchical_soft_min_distance(d_total_stack, artist_ranges, weights_arr)
    
    # Apply popularity and track count as distance adjustments
    # Negative slider = favor obscure/low-track artists, positive = favor mainstream/high-track
    if popularity != 0 and data.artist_popularity is not None:
        pop_weight = 0.6
        track_weight = 0.2
        # Center around actual median
        pop_adjustment = (data.artist_popularity - data.popularity_median) * popularity * pop_weight
        track_adjustment = (data.artist_track_count - 0.5) * popularity * track_weight
        d_total = d_total - pop_adjustment - track_adjustment
    
    # Use Gumbel noise for variety - gives controlled randomness while respecting relevance
    # Clamp n to dataset size and fix argpartition (kth is 0-indexed, so use n-1)
    n = min(SAMPLE_SIZE, len(d_total))
    k = n - 1  # argpartition kth parameter is 0-indexed
    if diversity > 0:
        # Add noise scaled by diversity level (0=None, 1=Low, 2=Medium, 3=High)
        noise_scale = VARIETY_NOISE_SCALE * diversity
        noise = np.random.gumbel(loc=0.0, scale=noise_scale, size=d_total.shape).astype(np.float32)
        d_noisy = d_total.astype(np.float32) + noise
        # Use argpartition for O(n) instead of O(n log n) argsort
        top_n_unsorted = np.argpartition(d_noisy, k)[:n]
        similar_indices = top_n_unsorted[np.argsort(d_noisy[top_n_unsorted])]
    else:
        top_n_unsorted = np.argpartition(d_total, k)[:n]
        similar_indices = top_n_unsorted[np.argsort(d_total[top_n_unsorted])]
    
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
    excluded = set(input_artists)
    if exclude_artists:
        excluded.update(exclude_artists)
    pool = similar_df.filter(~pl.col('artist_name').is_in(list(excluded)))
    
    # Group and aggregate - fetch one extra to detect if more candidates exist
    artist_stats_full = (
        pool.group_by('artist_name')
        .agg([
            # Get scores of top K tracks for this artist
            pl.col('score').sort(descending=True).head(tracks_per_artist).sum().alias('total_score'),
            pl.col('track_id').count().alias('track_count')
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
    
    recommendations = {}
    debug_info = {} if debug else None
    
    for row in artist_stats.iter_rows(named=True):
        artist = row['artist_name']
        artist_tracks = (
            pool.filter(pl.col('artist_name') == artist)
            .sort('score', descending=True)
            .head(tracks_per_artist)
        )
        
        # Build tracks with optional per-song debug data
        tracks = []
        for r in artist_tracks.iter_rows(named=True):
            track_info = {
                "track_id": r['track_id'],
                "track_name": r['track_name'],
                "genre": r.get('genre')
            }
            
            # Add per-song debug data if requested
            if debug and debug_audio:
                track_idx = lookup.get(r['track_id'])
                if track_idx is not None:
                    # Extract audio features for this specific song
                    key_features = ['energy', 'danceability', 'acousticness', 'valence', 'tempo', 'instrumentalness']
                    features_to_use = [c for c in key_features if c in data.audio_cols]
                    
                    audio_feats = {}
                    for feat in features_to_use:
                        idx = data.audio_cols.index(feat)
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
            genre_profile = data.artist_genre_profile.get(artist, [])
            artist_debug['genre_profile'] = [
                {"genre": g, "pct": p} for g, p in genre_profile
            ]
            debug_info[artist] = artist_debug
    
    meta = {
        "has_more_candidates": has_more_candidates,
    }
    if debug:
        meta["debug"] = debug_info
        # Include input artists genre profile for comparison
        input_profile = []
        for inp_artist in input_artists:
            profile = data.artist_genre_profile.get(inp_artist, [])
            if profile:
                input_profile.append({
                    "artist": inp_artist,
                    "genres": [{"genre": g, "pct": p} for g, p in profile]
                })
        meta["input_genre_profile"] = input_profile
        
        # Include search vector audio features if requested (average of seeds for display)
        if debug_audio and seeds_audio:
            key_features = ['energy', 'danceability', 'acousticness', 'valence', 'tempo', 'instrumentalness']
            features_to_use = [c for c in key_features if c in data.audio_cols]
            
            # Average seeds for debug display (actual search uses soft-min)
            avg_seed = np.mean(np.stack(seeds_audio, axis=0), axis=0)
            
            search_audio = {}
            for feat in features_to_use:
                idx = data.audio_cols.index(feat)
                raw_val = float(avg_seed[idx]) / FEATURE_WEIGHTS[feat]
                clamped_val = max(0.0, min(1.0, raw_val))
                search_audio[feat] = round(clamped_val, 3)
            
            meta["search_vector_audio"] = search_audio
            meta["num_seeds"] = len(seeds_audio)  # Show how many seeds are being used
        
        # Include search vector genre profile using actual text genres
        if debug_audio:
            # Build genre profile from input artists' tracks
            input_artist_df = df.filter(pl.col('artist_name').is_in(input_artists))
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
