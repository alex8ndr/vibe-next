"""
Recommendation logic for Vibe music recommendation app.
Updated to use polars instead of pandas for memory efficiency.
"""
import numpy as np
import polars as pl
from pathlib import Path
from typing import Protocol

FEATURE_WEIGHTS = {
    'popularity': 0.6,
    'year': 0.6,
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

DEFAULT_GENRE_WEIGHT = 2.0

# Composite "vibe" dimensions that map to multiple audio features
# Each maps a -1 to +1 slider to feature offsets
# Format: { 'feature_name': weight } - positive weight = feature increases with slider
VIBE_DIMENSIONS = {
    # Chill (-1) to Energetic (+1): affects energy, danceability, tempo, loudness
    'mood': {
        'energy': 1.0,
        'danceability': 0.0,
        'valence': 0.0,
        'loudness': 0.0,
    },
    # Acoustic (-1) to Electronic (+1): affects acousticness (inverted), instrumentalness
    'sound': {
        'acousticness': -1.0,  # Negative = acoustic decreases as slider goes up
        'liveness': 0,
        'instrumentalness': 0.5,
    },
}

# How strongly vibe sliders affect the search (in feature units, 0-1 scale)
VIBE_SLIDER_STRENGTH = 1

# Tracks to keep when computing representative vector for an artist 
ARTIST_SAMPLING_CURVE = [
    (5, 5),
    (20, 12),
    (50, 25),
    (80, 30),
]

# Number of tracks to recommend per artist
TRACKS_PER_ARTIST = 4

# Noise strength for variety control (easy to tune)
VARIETY_NOISE_SCALE = 0.15  # Higher = more randomness


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
        self.artists_list: list[str] = []
        self.audio_cols: list[str] = []
        self.genre_cols: list[str] = []
        self.track_id_to_idx: dict[str, int] = {}
        self.track_id_to_artist: dict[str, str] = {}  # For multi-song balancing
    
    def load(self) -> None:
        df = self.source.load()
        
        required = ['artist_name', 'track_name', 'track_id']
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        self.genre_cols = [c for c in df.columns if c.startswith('genre_')]
        self.audio_cols = [c for c in FEATURE_WEIGHTS.keys() if c in df.columns]
        
        # Audio Matrix (Weighted for Euclidean)
        audio_data = df.select(self.audio_cols).to_numpy().astype(np.float16)
        weights = np.array([FEATURE_WEIGHTS[c] for c in self.audio_cols], dtype=np.float16)
        self.matrix_audio = audio_data * weights
        
        # Genre Matrix (Unweighted for Cosine)
        self.matrix_genre = df.select(self.genre_cols).to_numpy().astype(np.float16)
        
        # Sort artists by popularity
        artist_popularity = (
            df.group_by('artist_name')
            .agg(pl.col('popularity').sum())
            .sort('popularity', descending=True)
        )
        self.artists_list = artist_popularity['artist_name'].to_list()
        
        # Build track_id lookups for O(1) access
        track_ids = df['track_id'].to_list()
        artist_names = df['artist_name'].to_list()
        self.track_id_to_idx = {tid: i for i, tid in enumerate(track_ids)}
        self.track_id_to_artist = {tid: artist for tid, artist in zip(track_ids, artist_names)}
        
        # Keep metadata for display/lookup
        keep_cols = ['artist_name', 'track_name', 'track_id']
        for col in ['popularity', 'genre']:
            if col in df.columns:
                keep_cols.append(col)
        
        self.df = df.select(keep_cols)


def euclidean_distance(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    diff = matrix - query
    return np.sqrt(np.sum(diff**2, axis=1))


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


def get_representative_vector(
    df: pl.DataFrame,
    matrix: np.ndarray,
    artists: list[str],
    track_id_to_idx: dict[str, int],
    track_ids: list[str] | None = None,
    track_id_to_artist: dict[str, str] | None = None
) -> np.ndarray | None:
    # All vectors stored as (vector, weight) tuples for consistent handling
    entity_vectors: list[tuple[np.ndarray, float]] = []
    
    # Track which artists have fine-tuned track selections
    artists_with_tracks = set()
    
    # Process fine-tuned track selections 
    if track_ids and track_id_to_artist:
        per_artist_vecs: dict[str, list[np.ndarray]] = {}
        for tid in track_ids:
            if tid in track_id_to_idx:
                artist = track_id_to_artist.get(tid, "unknown")
                if artist not in per_artist_vecs:
                    per_artist_vecs[artist] = []
                per_artist_vecs[artist].append(matrix[track_id_to_idx[tid]])
                artists_with_tracks.add(artist)
        
        # Average within each artist, weight by sqrt(n) for sublinear influence
        for artist, vecs in per_artist_vecs.items():
            artist_avg = np.mean(np.stack(vecs, axis=0), axis=0)
            weight = np.sqrt(len(vecs))
            entity_vectors.append((artist_avg, weight))
    elif track_ids:
        # Fallback if no artist lookup available
        for tid in track_ids:
            if tid in track_id_to_idx:
                entity_vectors.append((matrix[track_id_to_idx[tid]], 1.0))
    
    # Process artists
    if artists:
        for artist in artists:
            artist_df = df.filter(pl.col("artist_name") == artist)
            
            if len(artist_df) > 0:
                total_songs = len(artist_df)
                
                curve_x, curve_y = zip(*ARTIST_SAMPLING_CURVE)
                n_target = np.interp(total_songs, curve_x, curve_y)
                n_songs = min(total_songs, int(n_target))
                
                # Get top tracks by popularity
                top_df = artist_df.sort('popularity', descending=True).head(n_songs)
                
                # O(1) index lookup via pre-built dict
                indices = [
                    track_id_to_idx[tid]
                    for tid in top_df['track_id'].to_list()
                    if tid in track_id_to_idx
                ]
                
                if indices:
                    artist_vec = np.mean(matrix[indices], axis=0)
                    # Weight artist vectors by 0.5 to be less dominant when fine-tuned tracks exist
                    weight = 0.5 if artist in artists_with_tracks else 1.0
                    entity_vectors.append((artist_vec, weight))
    
    if not entity_vectors:
        return None
    
    # Weighted averaging
    vectors = np.stack([v[0] for v in entity_vectors], axis=0)
    weights = np.array([v[1] for v in entity_vectors])
    avg_vector = np.average(vectors, axis=0, weights=weights)
    
    return avg_vector.reshape(1, -1)


def generate_recommendations(
    data: MusicData,
    input_artists: list[str],
    track_ids: list[str] | None = None,
    exclude_artists: list[str] | None = None,
    diversity: int = 2,
    max_artists: int = 6,
    genre_weight: float = DEFAULT_GENRE_WEIGHT,
    tracks_per_artist: int = TRACKS_PER_ARTIST,
    vibe_modifiers: dict[str, float] | None = None,  # e.g., {'mood': 0.5, 'sound': -0.3}
    popularity: float = 0.0  # -1 (hidden gems) to +1 (mainstream)
) -> dict[str, list[dict]]:
    df = data.df
    matrix_audio = data.matrix_audio
    matrix_genre = data.matrix_genre
    lookup = data.track_id_to_idx
    artist_lookup = data.track_id_to_artist
    
    vec_audio = get_representative_vector(df, matrix_audio, input_artists, lookup, track_ids, artist_lookup)
    vec_genre = get_representative_vector(df, matrix_genre, input_artists, lookup, track_ids, artist_lookup)
    
    if vec_audio is None or vec_genre is None:
        return {}
    
    # Apply vibe modifiers to audio vector
    if vibe_modifiers:
        vec_audio = vec_audio.copy().astype(np.float32)
        for vibe_name, slider_value in vibe_modifiers.items():
            if vibe_name in VIBE_DIMENSIONS and slider_value != 0:
                for feature, weight in VIBE_DIMENSIONS[vibe_name].items():
                    if feature in data.audio_cols:
                        idx = data.audio_cols.index(feature)
                        # Apply offset: slider_value * weight * strength
                        offset = slider_value * weight * VIBE_SLIDER_STRENGTH
                        vec_audio[0, idx] += offset
    
    d_audio = euclidean_distance(vec_audio, matrix_audio)
    d_genre = cosine_distance(vec_genre, matrix_genre)
    
    d_total = np.sqrt(d_audio**2 + (d_genre * genre_weight)**2)
    
    # Apply popularity bias
    if popularity != 0:
        pop_idx = data.audio_cols.index('popularity')
        pop_values = data.matrix_audio[:, pop_idx] / FEATURE_WEIGHTS['popularity']
        # positive popularity = prefer mainstream (higher pop values)
        # negative popularity = prefer hidden gems (lower pop values)
        pop_bias = popularity * 0.3 * (pop_values - 0.5)
        d_total = d_total - pop_bias
    
    # Use Gumbel noise for variety - gives controlled randomness while respecting relevance
    n = 200 * diversity
    if diversity > 1:
        # Add noise scaled by diversity level
        noise_scale = VARIETY_NOISE_SCALE * (diversity - 1)
        noise = np.random.gumbel(loc=0.0, scale=noise_scale, size=d_total.shape).astype(np.float32)
        d_noisy = d_total.astype(np.float32) + noise
        similar_indices = d_noisy.argsort()[:n]
    else:
        similar_indices = d_total.argsort()[:n]
    
    # Get similar songs and add score (higher = better, based on position in sorted list)
    similar_df = df[similar_indices.tolist()]
    scores = np.arange(n, 0, -1)
    similar_df = similar_df.with_columns(pl.Series("score", scores))
    
    # Exclude input artists and any explicitly excluded artists
    excluded = set(input_artists)
    if exclude_artists:
        excluded.update(exclude_artists)
    pool = similar_df.filter(~pl.col('artist_name').is_in(list(excluded)))
    
    # Group and aggregate
    artist_stats = (
        pool.group_by('artist_name')
        .agg([
            pl.col('score').sum().alias('total_score'),
            pl.col('track_id').count().alias('track_count')
        ])
        .filter(pl.col('track_count') >= 2)
        .sort('total_score', descending=True)
        .head(max_artists)
    )
    
    recommendations = {}
    for row in artist_stats.iter_rows(named=True):
        artist = row['artist_name']
        artist_tracks = (
            pool.filter(pl.col('artist_name') == artist)
            .sort('score', descending=True)
            .head(tracks_per_artist)
        )
        
        tracks = [
            {
                "track_id": r['track_id'],
                "track_name": r['track_name'],
                "genre": r.get('genre')
            }
            for r in artist_tracks.iter_rows(named=True)
        ]
        recommendations[artist] = tracks
    
    return recommendations
