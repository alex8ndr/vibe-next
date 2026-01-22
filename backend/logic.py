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

# Tracks to keep when computing representative vector for an artist 
ARTIST_SAMPLING_CURVE = [
    (5, 5),
    (20, 12),
    (50, 25),
    (80, 30),
]

# Number of tracks to recommend per artist
TRACKS_PER_ARTIST = 4


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
    track_ids: list[str] | None = None
) -> np.ndarray | None:
    entity_vectors = []
    
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
                
                # Get row indices in original df (in polars, use row_nr() or join)
                indices = []
                for row in top_df.iter_rows(named=True):
                    # Find matching row in original df
                    mask = (df['track_id'] == row['track_id'])
                    idx = mask.arg_true()
                    if len(idx) > 0:
                        indices.append(idx[0])
                
                if indices:
                    artist_vec = np.mean(matrix[indices], axis=0)
                    entity_vectors.append(artist_vec)
    
    if track_ids:
        for tid in track_ids:
            mask = df['track_id'] == tid
            idx = mask.arg_true()
            if len(idx) > 0:
                track_vec = matrix[idx[0]]
                entity_vectors.append(track_vec)
    
    if not entity_vectors:
        return None
    
    combined = np.stack(entity_vectors, axis=0)
    avg_vector = np.mean(combined, axis=0)
    
    return avg_vector.reshape(1, -1)


def generate_recommendations(
    data: MusicData,
    input_artists: list[str],
    track_ids: list[str] | None = None,
    diversity: int = 2,
    max_artists: int = 6,
    genre_weight: float = DEFAULT_GENRE_WEIGHT
) -> dict[str, list[dict]]:
    df = data.df
    matrix_audio = data.matrix_audio
    matrix_genre = data.matrix_genre
    
    vec_audio = get_representative_vector(df, matrix_audio, input_artists, track_ids)
    vec_genre = get_representative_vector(df, matrix_genre, input_artists, track_ids)
    
    if vec_audio is None or vec_genre is None:
        return {}
    
    n = 200 * diversity
    
    d_audio = euclidean_distance(vec_audio, matrix_audio)
    d_genre = cosine_distance(vec_genre, matrix_genre)
    
    d_total = np.sqrt(d_audio**2 + (d_genre * genre_weight)**2)
    
    similar_indices = d_total.argsort()[:n]
    
    # Get similar songs and add score
    similar_df = df[similar_indices.tolist()]
    scores = np.arange(n, 0, -1)
    
    if diversity > 1:
        scores = np.random.permutation(scores)
    
    similar_df = similar_df.with_columns(pl.Series("score", scores))
    
    # Exclude input artists
    pool = similar_df.filter(~pl.col('artist_name').is_in(input_artists))
    
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
            .head(TRACKS_PER_ARTIST)
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
