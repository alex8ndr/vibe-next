"""
Shared utilities for data processing scripts.

Contains:
- ReccoBeatsClient: API client for ReccoBeats
- LastFmClient: API client for Last.fm related artists
- Genre lookup via TheAudioDB
- Track building and deduplication
- Weighted track sampling
- CSV loading/saving
"""
import os
import sys
import io
import zipfile
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set

import pandas as pd
import numpy as np
import requests

from track_dedup import deduplicate_tracks

# API endpoints
RECCOBEATS_URL = "https://api.reccobeats.com/v1"
DEEZER_URL = "https://api.deezer.com"
AUDIODB_URL = "https://www.theaudiodb.com/api/v1/json/2"
SONGLINK_URL = "https://api.song.link/v1-alpha.1/links"
LASTFM_URL = "https://ws.audioscrobbler.com/2.0"

# File paths (relative to backend/)
DATA_DIR = Path(__file__).parent.parent / "data"
MAIN_DATASET = DATA_DIR / "data.csv.zip"
OUTPUT_CSV = DATA_DIR / "added_artists.csv.zip"

# Raw columns (before processing)
RAW_COLS = [
    "artist_name", "track_name", "track_id", "popularity", "year", "genre",
    "danceability", "energy", "key", "loudness", "mode", "speechiness",
    "acousticness", "instrumentalness", "liveness", "valence", "tempo",
    "duration_ms", "time_signature"
]

# Feature weights for sampling (adapted from logic.py, simplified)
SAMPLING_WEIGHTS = {
    'popularity': 0.4,
    'acousticness': 1.0,
    'danceability': 1.0,
    'energy': 1.0,
    'valence': 1.0,
    'instrumentalness': 0.8,
    'speechiness': 0.6,
    'tempo': 0.6,
}

# TheAudioDB genre → dataset genre mapping
AUDIODB_GENRE_MAP = {
    # Rock variants
    'rock': 'rock', 'classic rock': 'rock', 'hard rock': 'hard-rock',
    'alternative rock': 'alt-rock', 'indie rock': 'indie-pop', 'indie': 'indie-pop',
    'psychedelic rock': 'psych-rock', 'progressive rock': 'rock', 'art rock': 'alt-rock',
    'garage rock': 'garage', 'grunge': 'alt-rock', 'post-punk': 'punk-rock',
    
    # Metal
    'metal': 'metal', 'heavy metal': 'heavy-metal', 'thrash metal': 'metal',
    'death metal': 'death-metal', 'black metal': 'black-metal', 'doom metal': 'metal',
    'nu metal': 'metal', 'metalcore': 'metalcore', 'industrial metal': 'industrial',
    'gothic metal': 'goth', 'symphonic metal': 'goth', 'progressive metal': 'metal',
    
    # Punk
    'punk': 'punk', 'punk rock': 'punk-rock', 'pop punk': 'punk', 'hardcore': 'hardcore',
    'post-hardcore': 'hardcore', 'emo': 'emo', 'screamo': 'emo',
    
    # Pop
    'pop': 'pop', 'dance pop': 'dance', 'electropop': 'electro', 'synth-pop': 'electro',
    'teen pop': 'pop', 'bubblegum pop': 'pop', 'power pop': 'power-pop',
    
    # K-Pop / Asian
    'k-pop': 'k-pop', 'j-pop': 'k-pop', 'c-pop': 'cantopop', 'mandopop': 'cantopop',
    
    # Hip-Hop / R&B
    'hip hop': 'hip-hop', 'hip-hop': 'hip-hop', 'rap': 'hip-hop', 'trap': 'hip-hop',
    'r&b': 'soul', 'rnb': 'soul', 'soul': 'soul', 'neo soul': 'soul', 'funk': 'funk',
    'gospel': 'gospel',
    
    # Electronic
    'electronic': 'electronic', 'edm': 'edm', 'house': 'house', 'deep house': 'deep-house',
    'techno': 'techno', 'trance': 'trance', 'dubstep': 'dubstep', 'drum and bass': 'drum-and-bass',
    'ambient': 'ambient', 'downtempo': 'chill', 'chillout': 'chill', 'trip hop': 'trip-hop',
    'industrial': 'industrial', 'electro': 'electro', 'disco': 'disco',
    
    # Acoustic / Folk / Country
    'folk': 'folk', 'acoustic': 'acoustic', 'singer-songwriter': 'singer-songwriter',
    'country': 'country', 'americana': 'country', 'bluegrass': 'folk',
    
    # Jazz / Blues
    'jazz': 'jazz', 'blues': 'blues', 'swing': 'jazz', 'bebop': 'jazz',
    
    # Latin
    'latin': 'salsa', 'salsa': 'salsa', 'reggaeton': 'dancehall', 'bossa nova': 'samba',
    'samba': 'samba', 'tango': 'tango',
    
    # Reggae
    'reggae': 'dancehall', 'ska': 'ska', 'dancehall': 'dancehall', 'dub': 'dub',
    
    # Classical
    'classical': 'classical', 'opera': 'opera', 'orchestral': 'classical',
    'soundtrack': 'pop-film', 'musical': 'show-tunes',
    
    # World
    'world': 'indian', 'indian': 'indian', 'bollywood': 'pop-film',
}


# Caches
_genre_cache: Dict[str, Optional[str]] = {}
_lastfm_api_key: Optional[str] = None


def get_lastfm_api_key() -> Optional[str]:
    """Get Last.fm API key from environment."""
    global _lastfm_api_key
    if _lastfm_api_key is None:
        _lastfm_api_key = os.environ.get("LASTFM_API_KEY", "")
    return _lastfm_api_key if _lastfm_api_key else None


class ReccoBeatsClient:
    """Client for ReccoBeats API."""
    TIMEOUT = 20

    def get_tracks(self, spotify_ids: List[str]) -> List[Dict]:
        if not spotify_ids:
            return []
        url = f"{RECCOBEATS_URL}/track"
        r = requests.get(url, params={"ids": ",".join(spotify_ids)}, timeout=self.TIMEOUT)
        r.raise_for_status()
        return r.json().get("content", [])

    def get_artist(self, recco_uuid: str) -> Dict:
        url = f"{RECCOBEATS_URL}/artist/{recco_uuid}"
        r = requests.get(url, timeout=self.TIMEOUT)
        r.raise_for_status()
        return r.json()

    def get_artist_tracks(self, recco_uuid: str, limit: int = 20) -> List[Dict]:
        fetch_limit = (limit * 3 + 49) // 50 * 50
        tracks = []
        page = 0
        while len(tracks) < fetch_limit:
            url = f"{RECCOBEATS_URL}/artist/{recco_uuid}/track"
            r = requests.get(url, params={"page": page, "size": 50}, timeout=self.TIMEOUT)
            r.raise_for_status()
            batch = r.json().get("content", [])
            if not batch:
                break
            tracks.extend(batch)
            page += 1
        
        tracks.sort(key=lambda t: t.get("popularity", 0), reverse=True)
        return tracks[:limit]

    def get_audio_features(self, spotify_ids: List[str]) -> Dict[str, Dict]:
        if not spotify_ids:
            return {}
        features = {}
        # Batch at 40 to avoid API limit (50 IDs causes 400 errors)
        for i in range(0, len(spotify_ids), 40):
            batch = spotify_ids[i:i+40]
            url = f"{RECCOBEATS_URL}/audio-features"
            r = requests.get(url, params={"ids": ",".join(batch)}, timeout=self.TIMEOUT)
            r.raise_for_status()
            for feat in r.json().get("content", []):
                if feat and "href" in feat:
                    sid = feat["href"].split("/")[-1]
                    features[sid] = feat
        return features

    def get_album(self, spotify_id: str) -> Optional[Dict]:
        url = f"{RECCOBEATS_URL}/album"
        r = requests.get(url, params={"ids": spotify_id}, timeout=self.TIMEOUT)
        r.raise_for_status()
        albums = r.json().get("content", [])
        return albums[0] if albums else None

    def get_album_tracks(self, recco_uuid: str) -> List[Dict]:
        tracks = []
        page = 0
        while True:
            url = f"{RECCOBEATS_URL}/album/{recco_uuid}/track"
            r = requests.get(url, params={"page": page, "size": 50}, timeout=self.TIMEOUT)
            r.raise_for_status()
            data = r.json()
            batch = data.get("content", [])
            if not batch:
                break
            tracks.extend(batch)
            if page >= data.get("totalPages", 1) - 1:
                break
            page += 1
        return tracks


class LastFmClient:
    """Client for Last.fm API - related artist discovery."""
    TIMEOUT = 15
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_lastfm_api_key()
    
    def get_similar_artists(
        self, 
        artist_name: str, 
        limit: int = 10,
        min_match: float = 0.3,
    ) -> List[Dict]:
        """Get similar artists from Last.fm.
        
        Returns list of {"name": str, "match": float (0-1)} sorted by match score.
        """
        if not self.api_key:
            return []
        
        try:
            r = requests.get(
                LASTFM_URL,
                params={
                    "method": "artist.getsimilar",
                    "artist": artist_name,
                    "api_key": self.api_key,
                    "format": "json",
                    "limit": limit * 2,
                },
                timeout=self.TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            
            similar = data.get("similarartists", {}).get("artist", [])
            results = []
            for a in similar:
                match = float(a.get("match", 0))
                if match >= min_match:
                    results.append({
                        "name": a.get("name", ""),
                        "match": match,
                    })
            
            results.sort(key=lambda x: x["match"], reverse=True)
            return results[:limit]
        
        except Exception:
            return []
    
    def expand_artist_pool(
        self,
        seed_artists: List[str],
        existing_artists: Set[str],
        limit: int = 20,
        min_match: float = 0.4,
    ) -> List[Dict]:
        """Expand a list of seed artists to discover new related artists.
        
        Returns list of {"name": str, "match": float, "seed": str} for new artists.
        """
        if not self.api_key:
            return []
        
        candidates = {}
        
        for seed in seed_artists:
            similar = self.get_similar_artists(seed, limit=15, min_match=min_match)
            
            for artist in similar:
                name = artist["name"]
                if name in existing_artists or name in seed_artists:
                    continue
                
                if name not in candidates:
                    candidates[name] = {
                        "name": name,
                        "match": artist["match"],
                        "seed": seed,
                        "count": 1,
                    }
                else:
                    candidates[name]["count"] += 1
                    candidates[name]["match"] = max(candidates[name]["match"], artist["match"])
            
            time.sleep(0.2)
        
        results = list(candidates.values())
        results.sort(key=lambda x: (x["count"], x["match"]), reverse=True)
        return results[:limit]


def get_genre_from_audiodb(artist_name: str) -> Optional[str]:
    """Fetch artist genre from TheAudioDB and map to dataset genre."""
    try:
        url = f"{AUDIODB_URL}/search.php"
        r = requests.get(url, params={"s": artist_name}, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        artists = data.get("artists")
        if not artists:
            return None
        
        artist = artists[0]
        genre = artist.get("strGenre", "").lower().strip()
        style = artist.get("strStyle", "").lower().strip()
        
        for term in [genre, style]:
            if term in AUDIODB_GENRE_MAP:
                return AUDIODB_GENRE_MAP[term]
        
        for term in [genre, style]:
            for key, value in AUDIODB_GENRE_MAP.items():
                if key in term or term in key:
                    return value
        
        return None
    except Exception:
        return None


def get_cached_genre(artist_name: str) -> Optional[str]:
    """Get genre with caching to minimize TheAudioDB calls."""
    if artist_name not in _genre_cache:
        _genre_cache[artist_name] = get_genre_from_audiodb(artist_name)
    return _genre_cache[artist_name]


def infer_genre_from_related(
    artist_name: str,
    lastfm_client: Optional[LastFmClient] = None,
) -> Optional[str]:
    """Try to infer genre from related artists (fallback for unknown genre)."""
    if lastfm_client is None:
        lastfm_client = LastFmClient()
    
    if not lastfm_client.api_key:
        return None
    
    similar = lastfm_client.get_similar_artists(artist_name, limit=5, min_match=0.5)
    
    genre_votes = {}
    for artist in similar:
        genre = get_cached_genre(artist["name"])
        if genre:
            weight = artist["match"]
            genre_votes[genre] = genre_votes.get(genre, 0) + weight
    
    if not genre_votes:
        return None
    
    return max(genre_votes, key=genre_votes.get)


def resolve_genre(
    artist_name: str,
    genre_override: Optional[str] = None,
    skip_unknown: bool = True,
    use_related_fallback: bool = False,
    lastfm_client: Optional[LastFmClient] = None,
    verbose: bool = False,
) -> Optional[str]:
    """Resolve genre for an artist with configurable fallback behavior.
    
    Args:
        artist_name: Artist to look up
        genre_override: If provided, use this genre directly
        skip_unknown: If True, return None for unknown genres (skip the artist)
        use_related_fallback: If True and genre unknown, try to infer from related artists
        lastfm_client: Optional LastFmClient for related artist lookup
        verbose: Print genre resolution details
    
    Returns:
        Genre string or None if unknown and skip_unknown=True
    """
    if genre_override:
        if verbose:
            print(f"  Genre: {genre_override} (override)")
        return genre_override
    
    genre = get_cached_genre(artist_name)
    if genre:
        if verbose:
            print(f"  Genre: {genre}")
        return genre
    
    if use_related_fallback:
        genre = infer_genre_from_related(artist_name, lastfm_client)
        if genre:
            if verbose:
                print(f"  Genre: {genre} (inferred from related)")
            return genre
    
    if skip_unknown:
        if verbose:
            print(f"  Genre: unknown (skipping)")
        return None
    
    if verbose:
        print(f"  Genre: unknown (using 'pop' fallback)")
    return "pop"


def search_artist_via_deezer(artist_name: str, verbose: bool = False, quiet: bool = False) -> Optional[str]:
    """Search for artist on Deezer, convert track to Spotify via Songlink.
    
    Args:
        artist_name: Artist to search for
        verbose: Print extra details about search process
        quiet: Suppress all output (overrides verbose)
    """
    try:
        r = requests.get(f"{DEEZER_URL}/search/artist", params={"q": artist_name, "limit": 1}, timeout=10)
        r.raise_for_status()
        artists = r.json().get("data", [])
        if not artists:
            if not quiet:
                print(f"    Not found on Deezer")
            return None
        
        deezer_artist = artists[0]
        found_name = deezer_artist["name"]
        if not quiet:
            print(f"    Found: {found_name}")
        
        r = requests.get(f"{DEEZER_URL}/artist/{deezer_artist['id']}/top", params={"limit": 5}, timeout=10)
        r.raise_for_status()
        tracks = r.json().get("data", [])
        if not tracks:
            if not quiet:
                print(f"    No tracks on Deezer")
            return None
        
        for track in tracks:
            track_id = track.get("id")
            track_title = track.get("title", "")
            
            if verbose and not quiet:
                print(f"    Trying: {track_title}")
            
            try:
                deezer_url = f"https://deezer.com/track/{track_id}"
                r = requests.get(SONGLINK_URL, params={"url": deezer_url}, timeout=15)
                
                if r.status_code == 200:
                    data = r.json()
                    spotify_url = data.get("linksByPlatform", {}).get("spotify", {}).get("url")
                    
                    if spotify_url:
                        spotify_id = spotify_url.split("/")[-1].split("?")[0]
                        if not quiet:
                            print(f"    Matched: {track_title}")
                        return spotify_id
            except Exception:
                pass
            
            time.sleep(0.3)
        
        if not quiet:
            print(f"    Could not find Spotify link")
        return None
        
    except Exception as e:
        if not quiet:
            print(f"    Search failed: {e}")
        return None


def extract_spotify_id(url_or_id: str) -> Tuple[str, str]:
    """Extract Spotify ID and type from URL or return as-is."""
    if "spotify.com" in url_or_id:
        parts = url_or_id.split("/")
        spotify_id = parts[-1].split("?")[0]
        for i, part in enumerate(parts):
            if part in ("album", "track") and i + 1 < len(parts):
                return spotify_id, part
        return spotify_id, "track"
    return url_or_id, "track"


def build_rows(
    artist_name: str, 
    tracks: List[Dict], 
    features: Dict[str, Dict], 
    genre: Optional[str], 
    verbose: bool = False,
) -> pd.DataFrame:
    """Build DataFrame from API responses with RAW (unscaled) values."""
    rows = []
    
    for track in tracks:
        href = track.get("href", "")
        spotify_id = href.split("/")[-1] if href else None
        if not spotify_id:
            continue

        feat = features.get(spotify_id, {})
        
        rows.append({
            "artist_name": artist_name,
            "track_name": track.get("trackTitle", ""),
            "track_id": spotify_id,
            "popularity": track.get("popularity"),
            "year": None,
            "genre": genre or "unknown",
            "danceability": feat.get("danceability"),
            "energy": feat.get("energy"),
            "key": feat.get("key"),
            "loudness": feat.get("loudness"),
            "mode": feat.get("mode"),
            "speechiness": feat.get("speechiness"),
            "acousticness": feat.get("acousticness"),
            "instrumentalness": feat.get("instrumentalness"),
            "liveness": feat.get("liveness"),
            "valence": feat.get("valence"),
            "tempo": feat.get("tempo"),
            "duration_ms": track.get("durationMs"),
            "time_signature": feat.get("time_signature"),
        })

    df = pd.DataFrame(rows)
    for col in RAW_COLS:
        if col not in df.columns:
            df[col] = None
    
    return df[RAW_COLS]


def weighted_track_sample(
    tracks: List[Dict],
    features: Dict[str, Dict],
    target_count: int,
    diversity_weight: float = 0.4,
) -> List[Dict]:
    """Sample tracks using weighted scoring for diversity.
    
    Uses greedy Maximal Marginal Relevance: picks highest popularity first,
    then iteratively selects tracks that maximize popularity + distance from
    already-selected tracks. Features are min-max normalized so tempo doesn't
    dominate.
    
    Args:
        tracks: List of track dicts from API
        features: Audio features keyed by Spotify ID
        target_count: Number of tracks to select
        diversity_weight: How much to weight diversity vs popularity (0-1)
    
    Returns:
        Selected tracks in order of selection
    """
    if target_count <= 0:
        return []
    if len(tracks) <= target_count:
        return tracks
    
    diversity_weight = max(0.0, min(1.0, diversity_weight))
    
    # Extract features for each track
    feature_cols = list(SAMPLING_WEIGHTS.keys())
    track_data = []
    raw_features = []
    
    for t in tracks:
        href = t.get("href", "")
        sid = href.split("/")[-1] if href else None
        if not sid:
            continue
        
        feat = features.get(sid, {})
        pop = t.get("popularity", 0) or 0
        
        # Store raw feature values (will normalize later)
        row = []
        for col in feature_cols:
            val = feat.get(col)
            row.append(val if val is not None else np.nan)
        
        track_data.append({
            "track": t,
            "sid": sid,
            "popularity": pop,
        })
        raw_features.append(row)
    
    if not track_data:
        return tracks[:target_count]
    
    # Min-max normalize features per dimension
    feature_matrix = np.array(raw_features, dtype=np.float32)
    n_tracks, n_features = feature_matrix.shape
    
    for j in range(n_features):
        col = feature_matrix[:, j]
        valid = ~np.isnan(col)
        if valid.sum() == 0:
            feature_matrix[:, j] = 0.5
            continue
        
        col_min = col[valid].min()
        col_max = col[valid].max()
        col_range = col_max - col_min
        
        if col_range > 0:
            feature_matrix[valid, j] = (col[valid] - col_min) / col_range
        else:
            feature_matrix[valid, j] = 0.5
        
        # Fill NaNs with median of normalized values
        median_val = np.median(feature_matrix[valid, j])
        feature_matrix[~valid, j] = median_val
    
    # Apply feature weights after normalization
    weights = np.array([SAMPLING_WEIGHTS[c] for c in feature_cols], dtype=np.float32)
    feature_matrix = feature_matrix * weights
    
    # Store normalized features
    for i, td in enumerate(track_data):
        td["features"] = feature_matrix[i]
    
    # Normalize popularity scores
    pop_scores = np.array([t["popularity"] for t in track_data], dtype=np.float32)
    max_pop = pop_scores.max() if pop_scores.max() > 0 else 1.0
    
    # Greedy selection: start with most popular
    selected = []
    remaining = list(range(len(track_data)))
    
    first_idx = int(np.argmax(pop_scores))
    selected.append(first_idx)
    remaining.remove(first_idx)
    
    # Precompute max possible distance for normalization
    max_dist = np.sqrt(np.sum(weights ** 2))  # Max distance in weighted space
    
    while len(selected) < target_count and remaining:
        selected_features = np.stack([track_data[i]["features"] for i in selected])
        
        best_score = -np.inf
        best_idx = remaining[0]
        
        for idx in remaining:
            pop_score = pop_scores[idx] / max_pop
            
            # Min distance to any selected track (normalized to ~0-1)
            dists = np.linalg.norm(selected_features - track_data[idx]["features"], axis=1)
            min_dist = dists.min() / max_dist
            
            score = (1 - diversity_weight) * pop_score + diversity_weight * min_dist
            
            if score > best_score:
                best_score = score
                best_idx = idx
        
        selected.append(best_idx)
        remaining.remove(best_idx)
    
    return [track_data[i]["track"] for i in selected]


def load_existing() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load both main dataset and added_artists.csv.zip if they exist."""
    df_main = pd.DataFrame(columns=RAW_COLS)
    df_added = pd.DataFrame(columns=RAW_COLS)
    
    if os.path.exists(MAIN_DATASET):
        df_main = pd.read_csv(MAIN_DATASET)
    
    if os.path.exists(OUTPUT_CSV):
        df_added = pd.read_csv(OUTPUT_CSV)
    
    return df_main, df_added


def save_csv_zip(df: pd.DataFrame) -> None:
    """Save DataFrame to compressed CSV zip."""
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    
    with zipfile.ZipFile(OUTPUT_CSV, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("added_artists.csv", csv_buffer.getvalue())


def deduplicate_with_report(
    df_combined: pd.DataFrame, 
    df_main: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[str]]:
    """Deduplicate and return removed track names for reporting."""
    removed_tracks = []
    
    main_track_ids = set(df_main["track_id"].dropna().unique()) if not df_main.empty else set()
    mask_in_main = df_combined["track_id"].isin(main_track_ids)
    for artist, track in df_combined[mask_in_main][["artist_name", "track_name"]].values:
        removed_tracks.append(f"  - {artist} - {track} (already in dataset)")
    df_combined = df_combined[~mask_in_main]
    
    before = len(df_combined)
    df_combined = deduplicate_tracks(df_combined, track_col="track_name", artist_col="artist_name")
    n_removed = before - len(df_combined)
    if n_removed > 0:
        removed_tracks.append(f"  + {n_removed} similar track names removed")
    
    return df_combined, removed_tracks


def add_discovered_artist(
    artist_name: str,
    existing_track_ids: Set[str],
    skip_unknown: bool = True,
    use_infer: bool = False,
    tracks_per_artist: int = 15,
    diversity_weight: float = 0.3,
    verbose: bool = False,
    quiet: bool = False,
    lastfm_client: Optional["LastFmClient"] = None,
) -> Optional[pd.DataFrame]:
    """Fetch and add tracks for a discovered artist.
    
    Returns DataFrame of new tracks, or None if artist should be skipped.
    """
    spotify_id = search_artist_via_deezer(artist_name, verbose=verbose, quiet=quiet)
    if not spotify_id:
        if verbose:
            print(f"    Not found via Deezer")
        return None
    
    client = ReccoBeatsClient()
    tracks = client.get_tracks([spotify_id])
    if not tracks:
        if verbose:
            print(f"    Track not found on ReccoBeats")
        return None
    
    track = tracks[0]
    artists = track.get("artists", [])
    if not artists:
        return None
    
    artist_uuid = artists[0]["id"]
    confirmed_name = artists[0]["name"]
    
    genre = resolve_genre(
        confirmed_name,
        skip_unknown=skip_unknown,
        use_related_fallback=use_infer,
        lastfm_client=lastfm_client,
        verbose=verbose,
    )
    
    if genre is None:
        return None
    
    fetch_limit = tracks_per_artist * 3
    artist_tracks = client.get_artist_tracks(artist_uuid, fetch_limit)
    if not artist_tracks:
        if verbose:
            print(f"    No tracks found")
        return None
    
    new_tracks = [
        t for t in artist_tracks
        if t.get("href", "").split("/")[-1] not in existing_track_ids
    ]
    
    if not new_tracks:
        if verbose:
            print(f"    All tracks already in dataset")
        return None
    
    spotify_ids = [t.get("href", "").split("/")[-1] for t in new_tracks if t.get("href")]
    features = client.get_audio_features(spotify_ids)
    
    sampled = weighted_track_sample(
        new_tracks, 
        features, 
        target_count=tracks_per_artist,
        diversity_weight=diversity_weight,
    )
    
    df_new = build_rows(confirmed_name, sampled, features, genre, verbose)
    df_new = deduplicate_tracks(df_new, track_col="track_name")
    
    return df_new
