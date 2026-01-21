"""
Recommendation engine - ported from Streamlit app.
Handles vector similarity calculations for music recommendations.
"""

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from pathlib import Path
from typing import Protocol

# Audio Feature Weights (for Euclidean distance calculation)
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

# Genre Weight (for Cosine distance, combined with Audio distance)
DEFAULT_GENRE_WEIGHT = 2.0

# Artist Sampling Curve: (Total Tracks, Tracks to Keep)
ARTIST_SAMPLING_CURVE = [
    (5, 5),
    (20, 12),
    (50, 25),
    (80, 30),
]

TRACKS_PER_ARTIST = 4


class DataSource(Protocol):
    """Protocol for data sources - enables future extensibility (DB, API, etc.)"""
    def load(self) -> pd.DataFrame:
        ...


class ParquetDataSource:
    """Loads data from a local parquet file."""
    
    def __init__(self, path: Path):
        self.path = path
    
    def load(self) -> pd.DataFrame:
        return pd.read_parquet(self.path)


class MusicData:
    """
    Container for loaded music data and precomputed matrices.
    Designed to be loaded once at startup and reused.
    """
    
    def __init__(self, source: DataSource):
        self.source = source
        self.df: pd.DataFrame | None = None
        self.matrix_audio: np.ndarray | None = None
        self.matrix_genre: np.ndarray | None = None
        self.artists_list: list[str] = []
        self.audio_cols: list[str] = []
        self.genre_cols: list[str] = []
    
    def load(self) -> None:
        """Load data and precompute matrices. Call once at startup."""
        df = self.source.load()
        
        required = ['artist_name', 'track_name', 'track_id']
        if not all(col in df.columns for col in required):
            raise ValueError(f"Missing required columns: {required}")
        
        self.genre_cols = [c for c in df.columns if c.startswith('genre_')]
        self.audio_cols = [c for c in FEATURE_WEIGHTS.keys() if c in df.columns]
        
        # Audio Matrix (Weighted for Euclidean)
        audio_data = df[self.audio_cols].values.astype(np.float32)
        weights = np.array([FEATURE_WEIGHTS[c] for c in self.audio_cols], dtype=np.float32)
        self.matrix_audio = audio_data * weights
        
        # Genre Matrix (Unweighted for Cosine)
        self.matrix_genre = df[self.genre_cols].values.astype(np.float32)
        
        # Sort artists by popularity (most popular first)
        artist_popularity = (
            df.groupby('artist_name', observed=True)['popularity']
            .sum()
            .sort_values(ascending=False)
        )
        self.artists_list = artist_popularity.index.tolist()
        
        # Keep metadata for display/lookup
        keep_cols = ['artist_name', 'track_name', 'track_id']
        # Add display columns if they exist
        for col in ['popularity', 'genre', 'year']:
            if col in df.columns:
                keep_cols.append(col)
        
        self.df = df[keep_cols].copy()
        
        # Convert strings to categorical
        self.df['artist_name'] = self.df['artist_name'].astype('category')
        self.df['track_name'] = self.df['track_name'].astype('category')
        if 'genre' in self.df.columns:
            self.df['genre'] = self.df['genre'].astype('category')

    
    def reload(self) -> None:
        """Reload data from source. For future hot-reload capability."""
        self.load()


def get_representative_vector(
    df: pd.DataFrame,
    matrix: np.ndarray,
    artists: list[str],
    track_ids: list[str] | None = None
) -> np.ndarray | None:
    """
    Calculate representative vector for selected items.
    
    Each artist gets one representative mean vector (from their top N tracks).
    Each selected track is treated as a distinct entity.
    All entities are averaged together with equal weight.
    """
    entity_vectors = []
    
    if artists:
        for artist in artists:
            mask = df["artist_name"] == artist
            artist_df = df[mask]
            
            if len(artist_df) > 0:
                total_songs = len(artist_df)
                
                # Interpolate sample size from curve points
                curve_x, curve_y = zip(*ARTIST_SAMPLING_CURVE)
                n_target = np.interp(total_songs, curve_x, curve_y)
                n_songs = min(total_songs, int(n_target))
                
                artist_df = artist_df.copy()
                artist_df['popularity'] = artist_df['popularity'].astype(np.float32).fillna(0)
                
                top_indices = artist_df.nlargest(n_songs, 'popularity').index
                artist_vec = np.mean(matrix[top_indices], axis=0)
                entity_vectors.append(artist_vec)
    
    if track_ids:
        for tid in track_ids:
            mask = df["track_id"] == tid
            indices = np.where(mask)[0]
            if len(indices) > 0:
                track_vec = matrix[indices[0]]
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
    """
    Generate music recommendations based on selected artists/tracks.
    
    Returns dict mapping artist names to lists of track dicts.
    """
    df = data.df
    matrix_audio = data.matrix_audio
    matrix_genre = data.matrix_genre
    
    vec_audio = get_representative_vector(df, matrix_audio, input_artists, track_ids)
    vec_genre = get_representative_vector(df, matrix_genre, input_artists, track_ids)
    
    if vec_audio is None or vec_genre is None:
        return {}
    
    n = 200 * diversity
    
    # Calculate Audio Distance (Euclidean)
    d_audio = cdist(vec_audio, matrix_audio, metric="euclidean")[0]
    
    # Calculate Genre Distance (Cosine)
    d_genre = cdist(vec_genre, matrix_genre, metric="cosine")[0]
    
    # Combined Distance
    d_total = np.sqrt(d_audio**2 + (d_genre * genre_weight)**2)
    
    similar_indices = d_total.argsort()[:n]
    
    similar_songs = df.iloc[similar_indices].copy()
    similar_songs['score'] = np.arange(n, 0, -1)
    
    if diversity > 1:
        similar_songs['score'] = np.random.permutation(similar_songs['score'])
    
    # Exclude input artists
    pool = similar_songs[~similar_songs['artist_name'].isin(input_artists)]
    
    artist_scores = pool.groupby('artist_name', observed=True)['score'].sum()
    artist_counts = pool.groupby('artist_name', observed=True)['track_id'].count()
    
    # Require at least 2 songs in pool
    qualified = artist_scores[artist_counts >= 2].sort_values(ascending=False)
    
    recommendations = {}
    for artist in qualified.head(max_artists).index:
        artist_tracks = (
            pool[pool['artist_name'] == artist]
            .sort_values('score', ascending=False)
            .head(TRACKS_PER_ARTIST)
        )
        tracks = [
            {
                "track_id": row['track_id'],
                "track_name": row['track_name'],
                "year": int(row['year']) if 'year' in row else None,
                "genre": row['genre'] if 'genre' in row else None
            }
            for _, row in artist_tracks.iterrows()
        ]
        recommendations[artist] = tracks
    
    return recommendations
