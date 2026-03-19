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

# Effective language weight for each slider position (0=None, 1=Low, 2=Medium, 3=High, 4=Max)
LANGUAGE_WEIGHT_CURVE = [0, 0.2, 0.5, 1.0, 2.0]

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

# Language focus slider (0-4: None/Low/Medium/High/Max)
LANGUAGE_FOCUS = 2

# Variety/diversity level (0-3: None/Low/Medium/High)
VARIETY = 0

# Max artists to return
MAX_ARTISTS = 6

# Noise strength for variety control (easy to tune)
VARIETY_NOISE_SCALE = 0.1  # Higher = more randomness

# Sample size for Gumbel noise distribution
SAMPLE_SIZE = 5000

# Dynamic overfetch and sampled percentage by genre weight.
DYNAMIC_CANDIDATE_PLAN_BY_GENRE_WEIGHT: dict[int, dict[str, float | int | None]] = {
    0: {"overfetch": 20, "genre_target_ratio": None},
    1: {"overfetch": 25, "genre_target_ratio": 0.64},
    2: {"overfetch": 30, "genre_target_ratio": 0.32},
    3: {"overfetch": 40, "genre_target_ratio": 0.24},
    4: {"overfetch": 50, "genre_target_ratio": 0.16},
}

# Optional language-aware prefilter.
LANGUAGE_PREFILTER_ENABLED = True
LANGUAGE_PREFILTER_TARGET_RATIO_BY_WEIGHT: dict[int, float] = {
    2: 0.50,
    3: 0.40,
    4: 0.30,
}

# Limit temporary query allocations when scanning the full audio matrix.
# Each batch allocates roughly `batch_size * n_tracks * 4 bytes` for the
# temporary squared-distance buffer before reducing to a single min vector.
AUDIO_SCAN_SCRATCH_TARGET_MB = 96

# Spotify track IDs are typically 22 bytes; keep a lower bound so the lookup
# array stays fixed-width and compact even on tiny dev fixtures.
MIN_TRACK_ID_BYTES = 22


def _get_audio_scan_seed_batch_size(n_tracks: int, n_seeds: int) -> int:
    """Pick a seed-batch size that respects the scan scratch-memory target."""
    if n_tracks <= 0 or n_seeds <= 0:
        return 1
    bytes_per_seed = n_tracks * np.dtype(np.float32).itemsize
    max_batch = int((AUDIO_SCAN_SCRATCH_TARGET_MB * 1024 * 1024) // max(1, bytes_per_seed))
    return max(1, min(n_seeds, max_batch))


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
    def get_track_column_names(self) -> list[str]:
        ...

    def get_artist_column_names(self) -> list[str]:
        ...

    def load_tracks(self, columns: list[str] | None = None) -> pl.DataFrame:
        ...

    def load_artists(self, columns: list[str] | None = None) -> pl.DataFrame:
        ...


class ParquetDataSource:
    def __init__(self, tracks_path: Path, artists_path: Path):
        self.tracks_path = tracks_path
        self.artists_path = artists_path

    def get_track_column_names(self) -> list[str]:
        return pl.scan_parquet(self.tracks_path).collect_schema().names()

    def get_artist_column_names(self) -> list[str]:
        return pl.scan_parquet(self.artists_path).collect_schema().names()

    def load_tracks(self, columns: list[str] | None = None) -> pl.DataFrame:
        if columns is not None:
            return pl.scan_parquet(self.tracks_path).select(columns).collect()
        return pl.read_parquet(self.tracks_path)

    def load_artists(self, columns: list[str] | None = None) -> pl.DataFrame:
        if columns is not None:
            return pl.scan_parquet(self.artists_path).select(columns).collect()
        return pl.read_parquet(self.artists_path)


class MusicData:
    def __init__(self, source: DataSource):
        self.source = source
        self.track_count: int = 0
        self.matrix_audio: np.ndarray | None = None
        self.matrix_genre: np.ndarray | None = None
        self.matrix_genre_unit: np.ndarray | None = None
        self.audio_norms_sq: np.ndarray | None = None  # Precomputed ||x||² for fast distance
        self.genre_norms: np.ndarray | None = None  # Precomputed genre vector norms
        self.artists_list: list[str] = []
        self.artist_names_by_code: list[str] = []
        self.artist_names_sorted: np.ndarray | None = None
        self.artist_codes_sorted: np.ndarray | None = None
        self.audio_cols: list[str] = []
        self.audio_col_indices: dict[str, int] = {}
        self.genre_cols: list[str] = []
        self.track_ids_sorted: np.ndarray | None = None
        self.track_row_indices_sorted: np.ndarray | None = None
        self.track_sorted_pos_by_row: np.ndarray | None = None
        self.track_artist_codes: np.ndarray | None = None  # Per-track compact artist code
        self.track_popularity: np.ndarray | None = None
        self.track_name_blob: bytearray | None = None
        self.track_name_offsets: np.ndarray | None = None
        self.genre_names_by_code: list[str | None] = [None]
        self.language_names_by_code: list[str | None] = [None]
        self.artist_genre_codes_by_artist_code: np.ndarray | None = None
        self.artist_language_codes_by_artist_code: np.ndarray | None = None
        self.artist_track_offsets: np.ndarray | None = None
        self.artist_track_row_indices: np.ndarray | None = None
        self.artist_popularity_by_code: np.ndarray | None = None  # Per-artist popularity (0-1)
        self.artist_track_count_by_code: np.ndarray | None = None  # Per-artist log track count (0-1)
        self.popularity_median: float = 0.5  # Median artist popularity for centering
    
    def load(self) -> None:
        t0 = perf_counter()
        print("[startup] Inspecting split parquet schemas...")
        track_columns = self.source.get_track_column_names()
        artist_columns = self.source.get_artist_column_names()

        track_required = ['artist_name', 'track_name', 'track_id']
        artist_required = ['artist_name', 'genre', 'language']

        for col in track_required:
            if col not in track_columns:
                raise ValueError(f"Missing required tracks column: {col}")
        for col in artist_required:
            if col not in artist_columns:
                raise ValueError(f"Missing required artists column: {col}")

        self.genre_cols = [c for c in artist_columns if c.startswith('genre_')]
        if not self.genre_cols:
            raise ValueError("artists dataset is missing genre_* embedding columns")

        self.audio_cols = [c for c in FEATURE_WEIGHTS.keys() if c in track_columns]
        if not self.audio_cols:
            raise ValueError("tracks dataset is missing required audio feature columns")
        self.audio_col_indices = {col: idx for idx, col in enumerate(self.audio_cols)}

        track_meta_cols = track_required[:]
        if 'popularity' in track_columns:
            track_meta_cols.append('popularity')

        artist_meta_cols = ['artist_name', 'genre', 'language'] + self.genre_cols

        print(
            f"[startup] Loading artists ({len(artist_meta_cols)} cols incl {len(self.genre_cols)} genre dims)..."
        )
        artist_df = self.source.load_artists(artist_meta_cols)
        artist_df = artist_df.unique(subset=['artist_name'], keep='first')
        for col in artist_required:
            null_count = int(artist_df[col].null_count())
            if null_count > 0:
                raise ValueError(f"artists dataset has {null_count:,} rows with null {col}")

        artist_df = artist_df.with_row_index('artist_code')
        self.artist_names_by_code = artist_df['artist_name'].to_list()
        self._build_artist_lookup(self.artist_names_by_code)
        self.artist_genre_codes_by_artist_code = self._build_artist_genres(artist_df['genre'])
        self.artist_language_codes_by_artist_code = self._build_artist_languages(artist_df['language'])

        matrix_genre_f32 = artist_df.select(self.genre_cols).to_numpy().astype(np.float32, copy=False)
        self.genre_norms = np.einsum('ij,ij->i', matrix_genre_f32, matrix_genre_f32, dtype=np.float32)
        np.sqrt(self.genre_norms, out=self.genre_norms)
        self.genre_norms[self.genre_norms == 0] = 1.0
        self.matrix_genre_unit = (matrix_genre_f32 / self.genre_norms[:, None]).astype(np.float32, copy=False)
        self.matrix_genre = matrix_genre_f32.astype(np.float16)
        del matrix_genre_f32

        print(
            f"[startup] Loading track metadata ({len(track_meta_cols)} cols) and audio ({len(self.audio_cols)} cols)..."
        )
        meta_df = self.source.load_tracks(track_meta_cols).with_row_index('_source_row')
        print(f"[startup] Loaded tracks rows: {len(meta_df):,}")

        valid_mask = np.ones(len(meta_df), dtype=bool)
        for col in track_required:
            col_mask = meta_df[col].is_not_null().to_numpy()
            null_count = int((~col_mask).sum())
            if null_count > 0:
                print(f"Warning: Filtering {null_count} rows with null {col}")
                valid_mask &= col_mask
        if not valid_mask.all():
            meta_df = meta_df.filter(pl.Series(valid_mask))

        artist_catalog = artist_df.select(['artist_name', 'artist_code'])
        meta_df = meta_df.join(artist_catalog, on='artist_name', how='left')
        unknown_artist_rows = meta_df['artist_code'].null_count()
        if unknown_artist_rows > 0:
            print(f"Warning: Filtering {unknown_artist_rows:,} tracks without matching artist metadata")
            meta_df = meta_df.filter(pl.col('artist_code').is_not_null())

        source_row_indices = (
            meta_df['_source_row']
            .cast(pl.UInt32)
            .to_numpy()
            .astype(np.uint32, copy=False)
        )

        meta_df = meta_df.with_row_index('row_idx')
        self.track_count = len(meta_df)

        row_indices = (
            meta_df['row_idx']
            .cast(pl.UInt32)
            .to_numpy()
            .astype(np.uint32, copy=False)
        )
        self.track_artist_codes = (
            meta_df['artist_code']
            .cast(pl.UInt32)
            .to_numpy()
            .astype(np.uint32, copy=False)
        )

        if 'popularity' in meta_df.columns:
            self.track_popularity = (
                meta_df['popularity']
                .fill_null(0.0)
                .cast(pl.Float32)
                .to_numpy()
                .astype(np.float32, copy=False)
            )
        else:
            self.track_popularity = np.zeros(self.track_count, dtype=np.float32)

        self._build_track_lookup(meta_df['track_id'])
        self._build_track_names(meta_df['track_name'])
        self._build_artist_track_index(self.track_artist_codes, row_indices, self.track_popularity)
        self._build_artist_popularity(meta_df)

        if 'popularity' in meta_df.columns:
            artist_popularity = (
                meta_df.group_by('artist_code')
                .agg(pl.col('popularity').sum().alias('popularity'))
                .sort('popularity', descending=True)
            )
        else:
            artist_popularity = (
                meta_df.group_by('artist_code')
                .agg(pl.len().alias('popularity'))
                .sort('popularity', descending=True)
            )
        self.artists_list = [
            self.artist_names_by_code[int(code)]
            for code in artist_popularity['artist_code'].to_list()
        ]
        print(f"[startup] Indexed {len(self.artists_list):,} artists by popularity")

        lookup_mb = (
            self.track_ids_sorted.nbytes
            + self.track_row_indices_sorted.nbytes
            + self.track_sorted_pos_by_row.nbytes
        ) / 1024**2
        print(f"[startup] Built compact track lookup ({lookup_mb:.0f}MB)")

        del artist_popularity, artist_catalog, row_indices
        _trim_process_memory()

        print(f"[startup] Building audio matrix ({len(self.audio_cols)} cols)...")
        audio_df = self.source.load_tracks(self.audio_cols)
        audio_data = audio_df.to_numpy().astype(np.float32, copy=False)
        audio_data = audio_data[source_row_indices]
        weights = np.array([FEATURE_WEIGHTS[c] for c in self.audio_cols], dtype=np.float32)
        audio_data *= weights
        self.matrix_audio = audio_data
        self.audio_norms_sq = np.einsum('ij,ij->i', self.matrix_audio, self.matrix_audio, dtype=np.float32)

        del audio_df, audio_data, weights, source_row_indices, meta_df, artist_df, valid_mask

        audio_mb = self.matrix_audio.nbytes / 1024**2
        genre_mb = self.matrix_genre.nbytes / 1024**2
        print(f"[startup] Matrices ready (audio {audio_mb:.0f}MB f32 + genre {genre_mb:.0f}MB f16 @ artist-level)")

        _trim_process_memory()

        elapsed = perf_counter() - t0
        print(f"[startup] MusicData load complete in {elapsed:.2f}s")

    def _build_artist_lookup(self, artist_names: list[str]) -> None:
        if not artist_names:
            self.artist_names_sorted = np.empty(0, dtype='S1')
            self.artist_codes_sorted = np.empty(0, dtype=np.uint32)
            return

        max_len = max(1, max(len(name.encode('utf-8')) for name in artist_names))
        encoded = np.fromiter(
            (name.encode('utf-8') for name in artist_names),
            dtype=np.dtype(f'S{max_len}'),
            count=len(artist_names),
        )
        codes = np.arange(len(artist_names), dtype=np.uint32)
        order = np.argsort(encoded, kind='mergesort')
        self.artist_names_sorted = encoded[order]
        self.artist_codes_sorted = codes[order]

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

        self.track_ids_sorted = encoded[sorted_row_indices]
        self.track_row_indices_sorted = sorted_row_indices
        self.track_sorted_pos_by_row = sorted_positions

    def _build_track_names(self, track_names: pl.Series) -> None:
        byte_lengths = track_names.str.len_bytes().fill_null(0).to_numpy().astype(np.uint32, copy=False)
        total_bytes = int(byte_lengths.astype(np.uint64, copy=False).sum())
        offset_dtype = np.uint32 if total_bytes <= np.iinfo(np.uint32).max else np.uint64
        offsets = np.empty(len(track_names) + 1, dtype=offset_dtype)
        offsets[0] = 0
        np.cumsum(byte_lengths, dtype=offset_dtype, out=offsets[1:])

        blob = bytearray(total_bytes)
        blob_view = memoryview(blob)
        cursor = 0
        for value, size in zip(track_names, byte_lengths):
            if size:
                encoded = value.encode('utf-8')
                blob_view[cursor:cursor + int(size)] = encoded
                cursor += int(size)

        self.track_name_blob = blob
        self.track_name_offsets = offsets

    def _build_artist_genres(self, genres: pl.Series) -> np.ndarray:
        unique_genres = genres.drop_nulls().unique(maintain_order=True).to_list()
        genre_values = [None] + unique_genres
        dtype = np.uint16 if len(genre_values) <= np.iinfo(np.uint16).max else np.uint32
        mapping = pl.Series(unique_genres)
        codes_series = genres.replace_strict(
            mapping,
            pl.Series(range(1, len(unique_genres) + 1), dtype=pl.UInt32),
            default=0,
        )
        self.genre_names_by_code = genre_values
        return codes_series.to_numpy().astype(dtype, copy=False)

    def _build_artist_languages(self, language_col: pl.Series) -> np.ndarray:
        unique_langs = language_col.drop_nulls().unique(maintain_order=True).to_list()
        lang_values = [None] + unique_langs
        dtype = np.uint16 if len(lang_values) <= np.iinfo(np.uint16).max else np.uint32
        mapping = pl.Series(unique_langs)
        codes_series = language_col.replace_strict(
            mapping,
            pl.Series(range(1, len(unique_langs) + 1), dtype=pl.UInt32),
            default=0,
        )
        self.language_names_by_code = lang_values
        return codes_series.to_numpy().astype(dtype, copy=False)

    def _build_artist_track_index(
        self,
        artist_codes: np.ndarray,
        row_indices: np.ndarray,
        popularity: np.ndarray,
    ) -> None:
        order = np.lexsort((row_indices, -popularity, artist_codes))
        sorted_rows = row_indices[order].astype(np.uint32, copy=False)
        counts = np.bincount(artist_codes.astype(np.int64, copy=False), minlength=len(self.artist_names_by_code))
        offsets = np.empty(len(counts) + 1, dtype=np.uint32)
        offsets[0] = 0
        np.cumsum(counts, dtype=np.uint32, out=offsets[1:])

        self.artist_track_row_indices = sorted_rows
        self.artist_track_offsets = offsets
    
    def _build_artist_popularity(self, df: pl.DataFrame) -> None:
        """Build per-artist popularity and track count arrays for the popularity slider."""
        if 'popularity' in df.columns:
            artist_stats = (
                df.group_by('artist_code')
                .agg([
                    pl.col('popularity').cast(pl.Float32).mean().alias('avg_pop'),
                    pl.len().alias('track_count')
                ])
                .sort('artist_code')
            )
        else:
            artist_stats = (
                df.group_by('artist_code')
                .agg([
                    pl.lit(0.5).cast(pl.Float32).alias('avg_pop'),
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

    def _profile_for_artist_code(
        self,
        artist_code: int,
        *,
        code_values: np.ndarray | None,
        code_names: list[str | None],
    ) -> list[tuple[str, float]]:
        if code_values is None:
            return []
        if artist_code < 0 or artist_code >= len(code_values):
            return []
        code = int(code_values[artist_code])
        if code <= 0 or code >= len(code_names):
            return []
        label = code_names[code]
        if not label:
            return []
        return [(label, 100.0)]

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

    def get_track_name(self, row_idx: int) -> str:
        if self.track_name_blob is None or self.track_name_offsets is None:
            raise KeyError(f"Track row {row_idx} is unavailable")
        start = int(self.track_name_offsets[row_idx])
        end = int(self.track_name_offsets[row_idx + 1])
        return self.track_name_blob[start:end].decode('utf-8')

    def get_track_genre(self, row_idx: int) -> str | None:
        if self.track_artist_codes is None or self.artist_genre_codes_by_artist_code is None:
            return None
        artist_code = int(self.track_artist_codes[row_idx])
        if artist_code < 0 or artist_code >= len(self.artist_genre_codes_by_artist_code):
            return None
        code = int(self.artist_genre_codes_by_artist_code[artist_code])
        if code == 0:
            return None
        return self.genre_names_by_code[code]

    def get_track_language(self, row_idx: int) -> str | None:
        if self.track_artist_codes is None or self.artist_language_codes_by_artist_code is None:
            return None
        artist_code = int(self.track_artist_codes[row_idx])
        if artist_code < 0 or artist_code >= len(self.artist_language_codes_by_artist_code):
            return None
        code = int(self.artist_language_codes_by_artist_code[artist_code])
        if code < 0 or code >= len(self.language_names_by_code):
            return None
        return self.language_names_by_code[code]

    def get_artist_code(self, artist_name: str) -> int | None:
        if self.artist_names_sorted is None or self.artist_codes_sorted is None:
            return None
        key = artist_name.encode('utf-8')
        pos = int(np.searchsorted(self.artist_names_sorted, key, side='left'))
        if pos >= len(self.artist_names_sorted) or self.artist_names_sorted[pos] != key:
            return None
        return int(self.artist_codes_sorted[pos])

    def get_artist_name(self, artist_code: int) -> str:
        return self.artist_names_by_code[artist_code]

    def get_artist_track_indices(self, artist_code: int, limit: int | None = None) -> np.ndarray:
        if self.artist_track_offsets is None or self.artist_track_row_indices is None:
            return np.empty(0, dtype=np.uint32)
        start = int(self.artist_track_offsets[artist_code])
        end = int(self.artist_track_offsets[artist_code + 1])
        if limit is not None:
            end = min(end, start + limit)
        return self.artist_track_row_indices[start:end]

    def get_artist_genre_profiles(self, artist_names: list[str]) -> dict[str, list[tuple[str, float]]]:
        ordered_artists = [artist for artist in dict.fromkeys(artist_names) if artist]
        profiles: dict[str, list[tuple[str, float]]] = {}
        for artist in ordered_artists:
            artist_code = self.get_artist_code(artist)
            if artist_code is None:
                profiles[artist] = []
                continue
            profiles[artist] = self._profile_for_artist_code(
                artist_code,
                code_values=self.artist_genre_codes_by_artist_code,
                code_names=self.genre_names_by_code,
            )
        return profiles

    def get_artist_language_profiles(self, artist_names: list[str]) -> dict[str, list[tuple[str, float]]]:
        ordered_artists = [artist for artist in dict.fromkeys(artist_names) if artist]
        profiles: dict[str, list[tuple[str, float]]] = {}
        for artist in ordered_artists:
            artist_code = self.get_artist_code(artist)
            if artist_code is None:
                profiles[artist] = []
                continue
            profiles[artist] = self._profile_for_artist_code(
                artist_code,
                code_values=self.artist_language_codes_by_artist_code,
                code_names=self.language_names_by_code,
            )
        return profiles
    



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
    matrix_audio = data.matrix_audio
    if matrix_audio is None:
        return {}

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

        # Take top tracks by popularity as candidates, then select diverse subset
        n_candidates = max_seeds * DIVERSITY_CANDIDATE_MULTIPLIER
        candidate_indices = [
            int(row_idx)
            for row_idx in data.get_artist_track_indices(artist_code, n_candidates)
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


def _infer_seed_language_preferences(
    data: MusicData,
    seed_artist_codes: np.ndarray,
    weights_arr: np.ndarray,
) -> tuple[np.ndarray, int | None]:
    if data.artist_language_codes_by_artist_code is None or seed_artist_codes.size == 0:
        return np.empty(0, dtype=np.int64), None

    seed_lang_codes = data.artist_language_codes_by_artist_code[seed_artist_codes].astype(np.int64, copy=False)
    weighted_votes = np.bincount(seed_lang_codes, weights=weights_arr)
    if weighted_votes.size == 0:
        return np.empty(0, dtype=np.int64), None

    primary_code = int(np.argmax(weighted_votes))

    valid_codes = np.flatnonzero(weighted_votes > 0).astype(np.int64, copy=False)
    valid_codes = valid_codes[valid_codes > 0]
    if valid_codes.size == 0:
        return np.empty(0, dtype=np.int64), (primary_code if primary_code > 0 else None)

    valid_weights = weighted_votes[valid_codes]
    valid_total = float(np.sum(valid_weights))
    if valid_total <= 0:
        return np.empty(0, dtype=np.int64), (primary_code if primary_code > 0 else None)

    # Keep multiple query languages when seed artists are meaningfully split.
    valid_shares = valid_weights / valid_total
    active_codes = valid_codes[valid_shares >= 0.25]
    if active_codes.size == 0 and primary_code > 0:
        active_codes = np.array([primary_code], dtype=np.int64)

    if active_codes.size > 0 and (primary_code <= 0 or not np.any(active_codes == primary_code)):
        top_idx = int(np.argmax(weighted_votes[active_codes]))
        primary_code = int(active_codes[top_idx])

    return active_codes.astype(np.int64, copy=False), (primary_code if primary_code > 0 else None)


def _clamp_ratio(value: float | int | None) -> float | None:
    if value is None:
        return None
    ratio = float(np.clip(float(value), 0.0, 1.0))
    return ratio if ratio > 0 else None


def _resolve_dynamic_candidate_plan(genre_weight: int) -> tuple[int, float | None]:
    default_plan = DYNAMIC_CANDIDATE_PLAN_BY_GENRE_WEIGHT[GENRE_FOCUS]
    plan = DYNAMIC_CANDIDATE_PLAN_BY_GENRE_WEIGHT.get(genre_weight, default_plan)
    overfetch = max(1, int(plan.get("overfetch", default_plan["overfetch"])))
    return overfetch, _clamp_ratio(plan.get("genre_target_ratio"))


def _resolve_language_prefilter_target_ratio(language_weight: int) -> float | None:
    return _clamp_ratio(LANGUAGE_PREFILTER_TARGET_RATIO_BY_WEIGHT.get(language_weight))


def _prefilter_artist_codes_by_genre(
    data: MusicData,
    seeds_genre_stack: np.ndarray,
    weights_arr: np.ndarray,
    target_ratio: float | None,
) -> np.ndarray | None:
    if (
        data.matrix_genre_unit is None
        or data.artist_track_offsets is None
        or data.matrix_audio is None
        or target_ratio is None
    ):
        return None

    target_tracks = int(round(len(data.matrix_audio) * target_ratio))
    if target_tracks <= 0:
        return None

    w_sum = float(weights_arr.sum())
    if w_sum <= 0:
        return None

    query_vec = np.sum(seeds_genre_stack * (weights_arr[:, None]), axis=0) / w_sum
    qn = float(np.linalg.norm(query_vec))
    if qn <= 0:
        return None
    query_vec = query_vec / qn

    sims = data.matrix_genre_unit @ query_vec
    artist_counts = np.diff(data.artist_track_offsets).astype(np.int64, copy=False)
    order = np.argsort(sims)[::-1]
    cumsum = np.cumsum(artist_counts[order])
    keep_n = int(np.searchsorted(cumsum, target_tracks, side='left') + 1)
    keep_n = max(1, min(keep_n, len(order)))
    return order[:keep_n].astype(np.int32, copy=False)


def _prefilter_artist_codes_by_language(
    data: MusicData,
    query_language_codes: np.ndarray,
    target_ratio: float | None,
) -> np.ndarray | None:
    if (
        data.artist_language_codes_by_artist_code is None
        or data.artist_track_offsets is None
        or data.matrix_audio is None
    ):
        return None
    if target_ratio is None or target_ratio <= 0:
        return None

    query_lang_codes = np.asarray(query_language_codes, dtype=np.int64)
    query_lang_codes = np.unique(query_lang_codes[query_lang_codes > 0])
    if query_lang_codes.size == 0:
        return None

    artist_lang_codes = data.artist_language_codes_by_artist_code.astype(np.int64, copy=False)
    artist_track_counts = np.diff(data.artist_track_offsets).astype(np.int64, copy=False)
    n_artists = min(len(artist_lang_codes), len(artist_track_counts))
    if n_artists == 0:
        return None

    artist_lang_codes = artist_lang_codes[:n_artists]
    artist_track_counts = artist_track_counts[:n_artists]

    target_tracks = int(round(len(data.matrix_audio) * target_ratio))
    if target_tracks <= 0:
        return None

    eligible_mask = np.isin(artist_lang_codes, query_lang_codes)
    if not bool(np.any(eligible_mask)):
        return None

    eligible_artist_indices = np.flatnonzero(eligible_mask).astype(np.int32, copy=False)
    eligible_track_counts = artist_track_counts[eligible_artist_indices]

    if data.artist_popularity_by_code is not None:
        artist_pop = data.artist_popularity_by_code[:n_artists].astype(np.float32, copy=False)
        eligible_pop = artist_pop[eligible_artist_indices]
    else:
        eligible_pop = np.zeros(len(eligible_artist_indices), dtype=np.float32)

    order = np.lexsort(
        (
            -eligible_track_counts.astype(np.float32, copy=False),
            -eligible_pop,
        )
    )
    ordered_artist_indices = eligible_artist_indices[order]
    ordered_track_counts = eligible_track_counts[order]
    cumsum = np.cumsum(ordered_track_counts)
    keep_n = int(np.searchsorted(cumsum, target_tracks, side='left') + 1)
    keep_n = max(1, min(keep_n, len(ordered_artist_indices)))
    return ordered_artist_indices[:keep_n].astype(np.int32, copy=False)


def generate_recommendations(
    data: MusicData,
    input_artists: list[str],
    track_ids: list[str] | None = None,
    exclude_artists: list[str] | None = None,
    diversity: int = VARIETY,
    max_artists: int = MAX_ARTISTS,
    genre_weight: int = GENRE_FOCUS,
    language_weight: int = LANGUAGE_FOCUS,
    tracks_per_artist: int = TRACKS_PER_ARTIST,
    vibe_modifiers: dict[str, float] | None = None,  # e.g., {'mood': 0.5, 'sound': -0.3}
    popularity: float = 0.0,  # -1 (hidden gems) to +1 (mainstream)
    debug: bool = False,
    debug_audio: bool = False,
) -> tuple[dict[str, list[dict]], dict]:
    t_start = perf_counter()
    matrix_audio = data.matrix_audio
    matrix_genre_unit = data.matrix_genre_unit
    audio_norms_sq = data.audio_norms_sq
    if (
        matrix_audio is None
        or matrix_genre_unit is None
        or data.track_artist_codes is None
        or audio_norms_sq is None
    ):
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
    seeds_audio_stack = matrix_audio[seed_index_arr]
    seed_artist_codes = data.track_artist_codes[seed_index_arr].astype(np.int32, copy=False)
    seeds_genre_stack = matrix_genre_unit[seed_artist_codes]
    applied_vibe_offsets = False
    
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
                applied_vibe_offsets = True

    if applied_vibe_offsets:
        seed_norms_sq_flat = np.einsum('ij,ij->i', seeds_audio_stack, seeds_audio_stack, dtype=np.float32)
    else:
        seed_norms_sq_flat = audio_norms_sq[seed_index_arr]

    weights_arr = np.asarray(weights, dtype=np.float32)

    # Clamp slider inputs to valid ranges and resolve effective weights once.
    genre_weight = int(np.clip(genre_weight, 0, len(GENRE_WEIGHT_CURVE) - 1))
    language_weight = int(np.clip(language_weight, 0, len(LANGUAGE_WEIGHT_CURVE) - 1))
    effective_genre_weight = GENRE_WEIGHT_CURVE[genre_weight]
    effective_language_weight = LANGUAGE_WEIGHT_CURVE[language_weight]

    query_language_code = None
    query_language_codes = np.empty(0, dtype=np.int64)
    if effective_language_weight > 0:
        query_language_codes, query_language_code = _infer_seed_language_preferences(
            data,
            seed_artist_codes,
            weights_arr,
        )

    overfetch_multiplier, genre_target_ratio = _resolve_dynamic_candidate_plan(genre_weight)

    language_target_ratio = None
    language_prefilter_ready = False
    if (
        LANGUAGE_PREFILTER_ENABLED
        and query_language_codes.size > 0
        and effective_language_weight > 0
        and data.artist_language_codes_by_artist_code is not None
    ):
        language_target_ratio = _resolve_language_prefilter_target_ratio(language_weight)
        language_prefilter_ready = language_target_ratio is not None

    genre_prefilter_artist_codes = None
    language_prefilter_artist_codes = None
    genre_prefilter_artist_codes = _prefilter_artist_codes_by_genre(
        data,
        seeds_genre_stack,
        weights_arr,
        genre_target_ratio,
    )
    if language_prefilter_ready and language_target_ratio is not None:
        language_prefilter_artist_codes = _prefilter_artist_codes_by_language(
            data,
            query_language_codes,
            language_target_ratio,
        )

    prefilter_artist_codes = None
    prefilter_mode = 'none'
    if genre_prefilter_artist_codes is not None and language_prefilter_artist_codes is not None:
        intersect_codes = np.intersect1d(
            genre_prefilter_artist_codes,
            language_prefilter_artist_codes,
            assume_unique=False,
        )
        if len(intersect_codes) > 0:
            prefilter_artist_codes = intersect_codes.astype(np.int32, copy=False)
            prefilter_mode = 'genre+language'
        else:
            prefilter_artist_codes = genre_prefilter_artist_codes
            prefilter_mode = 'genre-fallback'
    elif genre_prefilter_artist_codes is not None:
        prefilter_artist_codes = genre_prefilter_artist_codes
        prefilter_mode = 'genre'
    elif language_prefilter_artist_codes is not None:
        prefilter_artist_codes = language_prefilter_artist_codes
        prefilter_mode = 'language'

    candidate_scan_indices: np.ndarray | None = None
    if prefilter_artist_codes is not None and len(prefilter_artist_codes) > 0:
        artist_keep_mask = np.zeros(len(data.artist_names_by_code), dtype=bool)
        artist_keep_mask[prefilter_artist_codes] = True
        candidate_mask = artist_keep_mask[data.track_artist_codes]

        candidate_scan_indices = np.flatnonzero(candidate_mask).astype(np.int32, copy=False)
        if len(candidate_scan_indices) == 0:
            candidate_scan_indices = None

    if candidate_scan_indices is None:
        scan_audio = matrix_audio
        scan_audio_norms_sq = audio_norms_sq
        n_scan_tracks = len(matrix_audio)
    else:
        scan_audio = matrix_audio[candidate_scan_indices]
        scan_audio_norms_sq = audio_norms_sq[candidate_scan_indices]
        n_scan_tracks = len(candidate_scan_indices)
    
    t_prep = perf_counter()
    # Audio-only candidate generation: fast 12D matmul before full rerank.
    fetch_k = min(SAMPLE_SIZE * overfetch_multiplier, n_scan_tracks)
    
    # Reduce audio candidates in small seed batches so we never allocate a
    # full (num_seeds x num_tracks) distance matrix. The previous approach could
    # spike request-time RSS by hundreds of MB on large seed sets.
    scan_batch_size = _get_audio_scan_seed_batch_size(n_scan_tracks, len(seeds_audio_stack))
    d_audio_sq_min: np.ndarray | None = None
    for start in range(0, len(seeds_audio_stack), scan_batch_size):
        end = start + scan_batch_size
        batch = seeds_audio_stack[start:end]
        batch_norms_sq = seed_norms_sq_flat[start:end, None]
        batch_dots = batch @ scan_audio.T
        batch_dots *= -2.0
        batch_dots += scan_audio_norms_sq
        batch_dots += batch_norms_sq
        batch_min = np.min(batch_dots, axis=0)
        if d_audio_sq_min is None:
            d_audio_sq_min = batch_min
        else:
            np.minimum(d_audio_sq_min, batch_min, out=d_audio_sq_min)

    if fetch_k >= n_scan_tracks:
        top_k_idx = np.arange(n_scan_tracks, dtype=np.int32)
    else:
        top_k_idx = np.argpartition(d_audio_sq_min, fetch_k - 1)[:fetch_k].astype(np.int32, copy=False)
    if candidate_scan_indices is None:
        candidates = top_k_idx.astype(np.int32, copy=False)
    else:
        candidates = candidate_scan_indices[top_k_idx].astype(np.int32, copy=False)
    t_audio_scan = perf_counter()
    
    # Recompute per-seed audio distances only on the final candidate subset.
    candidate_audio = matrix_audio[candidates]
    candidate_audio_norms_sq = audio_norms_sq[candidates][None, :]
    seeds_norm_sq = seed_norms_sq_flat[:, None]
    dot_products_cand = seeds_audio_stack @ candidate_audio.T
    d_audio_sq = candidate_audio_norms_sq + seeds_norm_sq - 2.0 * dot_products_cand
    np.maximum(d_audio_sq, 0.0, out=d_audio_sq)
    del d_audio_sq_min, dot_products_cand
    
    t_audio = perf_counter()
    # Genre distance (cosine) computed ONLY on candidate subset.
    candidate_artist_codes = data.track_artist_codes[candidates].astype(np.int32, copy=False)
    cand_genre = matrix_genre_unit[candidate_artist_codes]
    genre_dots = seeds_genre_stack @ cand_genre.T
    d_genre = 1.0 - np.clip(genre_dots, -1.0, 1.0)
    
    t_genre = perf_counter()

    # Combined distance per seed
    d_total_stack = np.sqrt(d_audio_sq + (d_genre * effective_genre_weight)**2)
    
    # Hierarchical aggregation: low tau within artists, high tau between
    d_total = hierarchical_soft_min_distance(d_total_stack, artist_ranges, weights_arr)

    # Language distance term: d_lang = 0 when candidate language matches query language, else 1.
    if query_language_codes.size > 0 and effective_language_weight > 0 and data.artist_language_codes_by_artist_code is not None:
        candidate_lang_codes = data.artist_language_codes_by_artist_code[candidate_artist_codes].astype(np.int64, copy=False)
        d_lang = (~np.isin(candidate_lang_codes, query_language_codes)).astype(np.float32, copy=False)
        d_total = np.sqrt(d_total**2 + (d_lang * effective_language_weight)**2)
    t_language = perf_counter()
    
    # Apply popularity and track count as distance adjustments
    if popularity != 0 and data.artist_popularity_by_code is not None:
        pop_weight = 0.6
        track_weight = 0.2
        pop_adjustment = (data.artist_popularity_by_code[candidate_artist_codes] - data.popularity_median) * popularity * pop_weight
        track_adjustment = (data.artist_track_count_by_code[candidate_artist_codes] - 0.5) * popularity * track_weight
        d_total = d_total - pop_adjustment - track_adjustment
    t_adjust = perf_counter()
    
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

    # Zipfian scoring: rewards top matches significantly more than lower ones
    # Score = 1000 / (Rank + K)
    # scores = 1000.0 / (np.arange(1, n + 1) + 25.0)

    smoothing_factor = SAMPLE_SIZE * 0.025
    scores = 1000.0 / (np.arange(1, n + 1) + smoothing_factor)
    
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

    artist_buckets: dict[int, dict[str, object]] = {}
    for track_idx, score in zip(similar_indices.tolist(), scores.tolist()):
        artist_code = int(data.track_artist_codes[track_idx])
        if artist_code in excluded_codes:
            continue

        bucket = artist_buckets.setdefault(
            artist_code,
            {"track_count": 0, "total_score": 0.0, "tracks": []},
        )
        bucket["track_count"] = int(bucket["track_count"]) + 1
        top_tracks = bucket["tracks"]
        if len(top_tracks) < tracks_per_artist:
            top_tracks.append(track_idx)
            bucket["total_score"] = float(bucket["total_score"]) + float(score)

    artist_stats_full = [
        {
            "artist_code": artist_code,
            "track_count": int(bucket["track_count"]),
            "display_count": min(int(bucket["track_count"]), tracks_per_artist),
            "total_score": float(bucket["total_score"]),
            "tracks": list(bucket["tracks"]),
        }
        for artist_code, bucket in artist_buckets.items()
        if int(bucket["track_count"]) >= 2
    ]
    artist_stats_full.sort(key=lambda item: item["total_score"], reverse=True)
    has_more_candidates = len(artist_stats_full) > max_artists
    artist_stats = artist_stats_full[:max_artists]
    artist_stats.sort(key=lambda item: (item["display_count"], item["total_score"]), reverse=True)

    artist_profiles = (
        data.get_artist_genre_profiles(
            input_artists + [data.get_artist_name(int(row["artist_code"])) for row in artist_stats]
        )
        if debug else {}
    )
    language_profiles = (
        data.get_artist_language_profiles(
            input_artists + [data.get_artist_name(int(row["artist_code"])) for row in artist_stats]
        )
        if debug else {}
    )
    
    recommendations = {}
    debug_info = {} if debug else None
    
    for row in artist_stats:
        artist_code = int(row['artist_code'])
        artist = data.get_artist_name(artist_code)
        
        # Build tracks with optional per-song debug data
        tracks = []
        for track_idx in row['tracks']:
            genre = data.get_track_genre(track_idx)
            language = data.get_track_language(track_idx)
            track_info = {
                "track_id": data.get_track_id(track_idx),
                "track_name": data.get_track_name(track_idx),
                "genre": genre,
                "language": language,
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
                if genre:
                    audio_feats['genre'] = genre
                
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
            language_profile = language_profiles.get(artist, [])
            artist_debug['language_profile'] = [
                {"language": l, "pct": p} for l, p in language_profile
            ]
            debug_info[artist] = artist_debug
    
    t_postprocess = perf_counter()
    perf_info = {
        "seeds_ms": int(1000 * (t_seeds - t_start)),
        "prep_ms": int(1000 * (t_prep - t_seeds)),
        "audio_ms": int(1000 * (t_audio - t_prep)),
        "audio_scan_ms": int(1000 * (t_audio_scan - t_prep)),
        "audio_refine_ms": int(1000 * (t_audio - t_audio_scan)),
        "audio_scan_seed_batch": int(scan_batch_size),
        "overfetch": int(overfetch_multiplier),
        "candidate_pool": int(n_scan_tracks),
        "prefilter_mode": prefilter_mode,
        "prefilter_artists": int(0 if prefilter_artist_codes is None else len(prefilter_artist_codes)),
        "prefilter_genre_artists": int(0 if genre_prefilter_artist_codes is None else len(genre_prefilter_artist_codes)),
        "prefilter_language_artists": int(0 if language_prefilter_artist_codes is None else len(language_prefilter_artist_codes)),
        "genre_target_ratio": float(0.0 if genre_target_ratio is None else genre_target_ratio),
        "language_target_ratio": float(0.0 if language_target_ratio is None else language_target_ratio),
        "genre_ms": int(1000 * (t_genre - t_audio)),
        "lang_ms": int(1000 * (t_language - t_genre)),
        "adjust_ms": int(1000 * (t_adjust - t_language)),
        "rank_ms": int(1000 * (t_rank - t_adjust)),
        "post_ms": int(1000 * (t_postprocess - t_rank)),
        "total_ms": int(1000 * (t_postprocess - t_start)),
        "candidates": int(len(candidates)),
        "seed_count": int(len(seed_indices)),
    }
    print(f"[perf] seeds={1000*(t_seeds-t_start):.0f}ms prep={1000*(t_prep-t_seeds):.0f}ms "
          f"audio={1000*(t_audio-t_prep):.0f}ms audio_scan={1000*(t_audio_scan-t_prep):.0f}ms "
          f"audio_refine={1000*(t_audio-t_audio_scan):.0f}ms "
          f"genre={1000*(t_genre-t_audio):.0f}ms "
          f"lang={1000*(t_language-t_genre):.0f}ms adjust={1000*(t_adjust-t_language):.0f}ms "
          f"rank={1000*(t_rank-t_adjust):.0f}ms post={1000*(t_postprocess-t_rank):.0f}ms "
          f"TOTAL={1000*(t_postprocess-t_start):.0f}ms candidates={len(candidates)} "
          f"seeds={len(seed_indices)}")
    meta = {
        "has_more_candidates": has_more_candidates,
        "perf": perf_info,
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
        input_language_profile = []
        for inp_artist in input_artists:
            profile = language_profiles.get(inp_artist, [])
            if profile:
                input_language_profile.append({
                    "artist": inp_artist,
                    "languages": [{"language": l, "pct": p} for l, p in profile]
                })
        meta["input_language_profile"] = input_language_profile
        if query_language_code is not None:
            meta["query_language_code"] = query_language_code
            if 0 <= query_language_code < len(data.language_names_by_code):
                meta["query_language"] = data.language_names_by_code[query_language_code]
        if query_language_codes.size > 0:
            lang_codes = [int(code) for code in query_language_codes.tolist()]
            meta["query_language_codes"] = lang_codes
            meta["query_languages"] = [
                data.language_names_by_code[code]
                if 0 <= code < len(data.language_names_by_code)
                else None
                for code in lang_codes
            ]
        meta["effective_language_weight"] = effective_language_weight
        
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
        if debug_audio and data.artist_genre_codes_by_artist_code is not None:
            # Build genre profile from input artists' tracks
            input_artist_codes = [
                code
                for artist in input_artists
                if (code := data.get_artist_code(artist)) is not None
            ]
            genre_counts: dict[str, int] = {}
            for artist_code in input_artist_codes:
                for row_idx in data.get_artist_track_indices(artist_code):
                    genre = data.get_track_genre(int(row_idx))
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
