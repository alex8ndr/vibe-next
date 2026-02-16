"""
Shared utilities for data processing scripts.

Contains:
- ReccoBeatsClient: API client for ReccoBeats
- LastFmClient: API client for Last.fm related artists
- Genre lookup via TheAudioDB
- Track building and deduplication
- Weighted track sampling
- Parquet loading/saving
"""
import os
import sys
import io
import zipfile
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set

from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv
import polars as pl
import numpy as np
import requests

# Load environment variables from .env file (if it exists)
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


# =============================================================================
# DEFAULT CONSTANTS (for consistency across discovery scripts)
# =============================================================================
DEFAULT_TRACKS_PER_ARTIST = 25
DEFAULT_SEARCH_LIMIT = 50
DEFAULT_DIVERSITY_WEIGHT = 0.3
DEFAULT_MAX_ADD = 15          # Max artists to add in one run
DEFAULT_MIN_TRACKS = 3        # Min tracks for an artist to be added
DEFAULT_MIN_MATCH = 0.4       # Last.fm minimum match score
DEFAULT_BACKFILL_LIMIT = 50   # Artists to check for backfill
DEFAULT_EXPAND_LIMIT = 20     # Artists to discover via expansion
DEFAULT_TRENDING_LIMIT = 50   # Chart entries to check

from track_dedup import deduplicate_tracks_polars, normalize_artist_name
from schema import RAW_SCHEMA, RAW_COLUMN_ORDER, coerce_to_schema, normalize_for_merge

# API endpoints
RECCOBEATS_URL = "https://api.reccobeats.com/v1"
DEEZER_URL = "https://api.deezer.com"
AUDIODB_URL = "https://www.theaudiodb.com/api/v1/json/2"
SONGLINK_URL = "https://api.song.link/v1-alpha.1/links"
LASTFM_URL = "https://ws.audioscrobbler.com/2.0"

# Rate limits (seconds between requests)
# TheAudioDB: 30 req/min free tier → 2 sec minimum
# Songlink: 10 req/min without API key → 6 sec minimum  
# Deezer: 50 req/5sec → 0.1 sec minimum (generous at 0.2)
# Last.fm: Undocumented but reasonable use → 0.3 sec
# ReccoBeats: No documented limit → 0.2 sec
RATE_LIMIT_AUDIODB = 2.0
RATE_LIMIT_SONGLINK = 6.0
RATE_LIMIT_DEEZER = 0.2
RATE_LIMIT_LASTFM = 0.3
RATE_LIMIT_RECCOBEATS = 0.2

# File paths (relative to backend/)
DATA_DIR = Path(__file__).parent.parent / "data"
MAIN_DATASET = DATA_DIR / "data.parquet"  # Primary dataset (parquet)
OUTPUT_PARQUET = DATA_DIR / "added_artists.parquet"  # Discovery output (parquet)

# Legacy paths (for backward compatibility during migration)
LEGACY_CSV = DATA_DIR / "added_artists.csv.zip"
OUTPUT_CSV = LEGACY_CSV  # Alias for backward compat

# Use canonical column order from schema.py
RAW_COLS = RAW_COLUMN_ORDER

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

# TheAudioDB / Last.fm tag → dataset genre mapping
# NOTE: TheAudioDB often returns "rock/pop" for everything - we handle compound genres
AUDIODB_GENRE_MAP = {
    # === COMPOUND GENRES (TheAudioDB returns these frequently) ===
    'rock/pop': 'alt-rock',  # Most common TheAudioDB response - maps to modern alternative
    'pop/rock': 'alt-rock',
    'rock and roll': 'rock-n-roll',
    'pop rock': 'alt-rock',
    'indie pop': 'indie-pop',
    'indie rock': 'alt-rock',
    
    # === Rock variants ===
    'rock': 'rock', 'classic rock': 'rock', 'hard rock': 'hard-rock',
    'alternative rock': 'alt-rock', 'alternative': 'alt-rock', 'alt-rock': 'alt-rock',
    'indie': 'indie-pop', 'shoegaze': 'alt-rock', 'dream pop': 'indie-pop',
    'psychedelic rock': 'psych-rock', 'psychedelic': 'psych-rock', 'neo-psychedelia': 'psych-rock',
    'progressive rock': 'math-rock', 'prog rock': 'math-rock', 'art rock': 'psych-rock',
    'garage rock': 'garage', 'garage': 'garage', 'grunge': 'grunge', 'post-punk': 'punk-rock',
    'post-rock': 'psych-rock', 'noise rock': 'alt-rock', 'britpop': 'alt-rock',
    'new wave': 'alt-rock', 'post-punk revival': 'alt-rock',
    
    # === Metal ===
    'metal': 'metal', 'heavy metal': 'heavy-metal', 'thrash metal': 'metal', 'thrash': 'metal',
    'alternative metal': 'metal', 'alt metal': 'metal', 'alt-metal': 'metal',
    'death metal': 'death-metal', 'black metal': 'black-metal', 'doom metal': 'metal',
    'nu metal': 'metal', 'nu-metal': 'metal', 'metalcore': 'metalcore', 
    'industrial metal': 'industrial-metal', 'industrial': 'industrial',
    'gothic metal': 'goth', 'symphonic metal': 'goth', 'progressive metal': 'prog-metal',
    'prog metal': 'prog-metal', 'djent': 'prog-metal', 'groove metal': 'groove',
    'power metal': 'heavy-metal', 'melodic death metal': 'death-metal',
    'deathcore': 'metalcore', 'math metal': 'math-rock', 'speed metal': 'metal',
    'stoner metal': 'metal', 'sludge metal': 'metal',
    
    # === Punk ===
    'punk': 'punk', 'punk rock': 'punk-rock', 'pop punk': 'punk', 'pop-punk': 'punk',
    'hardcore': 'hardcore', 'hardcore punk': 'hardcore-punk',
    'post-hardcore': 'post-hardcore', 'emo': 'emo', 'screamo': 'emo', 'skate punk': 'punk',
    
    # === Pop ===
    'pop': 'pop', 'dance pop': 'dance', 'electropop': 'electro', 'synth-pop': 'electro',
    'synthpop': 'electro', 'synth pop': 'electro',
    'teen pop': 'pop', 'bubblegum pop': 'pop', 'power pop': 'power-pop',
    'art pop': 'pop', 'chamber pop': 'pop',
    
    # === K-Pop / Asian ===
    'k-pop': 'k-pop', 'kpop': 'k-pop', 'j-pop': 'j-pop', 'jpop': 'j-pop',
    'j-rock': 'j-rock', 'jrock': 'j-rock', 'visual kei': 'j-rock',
    'c-pop': 'cantopop', 'mandopop': 'cantopop', 'cantopop': 'cantopop',
    
    # === Hip-Hop / R&B ===
    'hip hop': 'hip-hop', 'hip-hop': 'hip-hop', 'hiphop': 'hip-hop',
    'rap': 'hip-hop', 'trap': 'hip-hop', 'underground hip-hop': 'hip-hop',
    'r&b': 'soul', 'rnb': 'soul', 'rhythm and blues': 'soul',
    'soul': 'soul', 'neo soul': 'soul', 'neo-soul': 'soul',
    'funk': 'funk', 'gospel': 'gospel',
    
    # === Electronic ===
    'electronic': 'electronic', 'electronica': 'electronic',
    'edm': 'edm', 'house': 'house', 'deep house': 'deep-house',
    'techno': 'techno', 'trance': 'trance', 'psytrance': 'trance',
    'dubstep': 'dubstep', 'drum and bass': 'drum-and-bass', 'dnb': 'drum-and-bass',
    'ambient': 'ambient', 'downtempo': 'chill', 'chillout': 'chill', 'chillwave': 'chill',
    'trip hop': 'trip-hop', 'trip-hop': 'trip-hop',
    'electro': 'electro', 'disco': 'disco', 'nu disco': 'disco',
    'idm': 'electronic', 'glitch': 'electronic', 'breakbeat': 'breakbeat',
    
    # === Acoustic / Folk / Country ===
    'folk': 'folk', 'acoustic': 'acoustic', 'singer-songwriter': 'singer-songwriter',
    'singer songwriter': 'singer-songwriter',
    'country': 'country', 'americana': 'country', 'bluegrass': 'folk',
    'folk rock': 'folk',
    
    # === Jazz / Blues ===
    'jazz': 'jazz', 'blues': 'blues', 'swing': 'jazz', 'bebop': 'jazz',
    'blues rock': 'blues', 'jazz fusion': 'jazz-fusion',
    
    # === Latin ===
    'latin': 'salsa', 'salsa': 'salsa', 'reggaeton': 'dancehall', 'latin pop': 'salsa',
    'bossa nova': 'samba', 'samba': 'samba', 'tango': 'tango',
    'latin rock': 'salsa', 'bachata': 'salsa',
    
    # === Reggae ===
    'reggae': 'reggae', 'ska': 'ska', 'dancehall': 'dancehall', 'dub': 'dub',
    'roots reggae': 'reggae',
    
    # === Classical ===
    'classical': 'classical', 'opera': 'opera', 'orchestral': 'classical',
    'soundtrack': 'pop-film', 'film score': 'pop-film', 'musical': 'show-tunes',
    'piano': 'piano', 'instrumental': 'acoustic',
    
    # === World / Regional ===
    'world': 'indian', 'indian': 'indian', 'bollywood': 'pop-film',
    'world music': 'indian', 'afrobeat': 'afrobeat', 'afrobeats': 'afrobeat',
    
    # === Christian / Worship ===
    'christian': 'ccm', 'ccm': 'ccm', 'christian rock': 'christian-rock',
    'worship': 'ccm', 'contemporary christian': 'ccm', 'christian metal': 'christian-metal',
    'praise': 'ccm',
    
    # === Math Rock / Progressive ===
    'math rock': 'math-rock', 'mathrock': 'math-rock',
    'progressive': 'math-rock', 'experimental': 'math-rock', 'avant-garde': 'math-rock',
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

    def __init__(self):
        self._album_tracks_cache: Dict[str, List[Dict]] = {}
    
    def get_artist_from_spotify_id(self, spotify_artist_id: str) -> Optional[Tuple[str, str]]:
        """Look up ReccoBeats artist UUID from Spotify artist ID.
        
        Returns:
            Tuple of (recco_uuid, artist_name) or None if not found
        """
        url = f"{RECCOBEATS_URL}/artist"
        r = requests.get(url, params={"ids": spotify_artist_id}, timeout=self.TIMEOUT)
        r.raise_for_status()
        content = r.json().get("content", [])
        if not content:
            return None
        return (content[0]["id"], content[0].get("name", "Unknown"))

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

    def search_artist(self, name: str, limit: int = 5) -> List[Dict]:
        """Search for artist by name. Returns list of {id, name, href}."""
        url = f"{RECCOBEATS_URL}/artist/search"
        r = requests.get(url, params={"searchText": name, "size": limit}, timeout=self.TIMEOUT)
        r.raise_for_status()
        return r.json().get("content", [])

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
        """Get all tracks for an album (with per-instance caching)."""
        if recco_uuid in self._album_tracks_cache:
            return self._album_tracks_cache[recco_uuid]
        
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
        
        self._album_tracks_cache[recco_uuid] = tracks
        return tracks

    def get_artist_albums(self, recco_uuid: str) -> List[Dict]:
        """Get all albums for an artist (paginated)."""
        albums = []
        page = 0
        while True:
            url = f"{RECCOBEATS_URL}/artist/{recco_uuid}/album"
            r = requests.get(url, params={"page": page, "size": 50}, timeout=self.TIMEOUT)
            r.raise_for_status()
            data = r.json()
            batch = data.get("content", [])
            if not batch:
                break
            albums.extend(batch)
            if page >= data.get("totalPages", 1) - 1:
                break
            page += 1
            time.sleep(0.2)
        return albums


class LastFmClient:
    """Client for Last.fm API - related artist discovery and tags."""
    TIMEOUT = 15
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_lastfm_api_key()
    
    def get_artist_tags(
        self,
        artist_name: str,
        limit: int = 5,
    ) -> List[Dict]:
        """Get top tags for an artist from Last.fm.
        
        Returns list of {"name": str, "count": int} sorted by count.
        Tags are user-generated and more granular than TheAudioDB genres.
        """
        if not self.api_key:
            return []
        
        try:
            r = requests.get(
                LASTFM_URL,
                params={
                    "method": "artist.gettoptags",
                    "artist": artist_name,
                    "api_key": self.api_key,
                    "format": "json",
                },
                timeout=self.TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            
            tags = data.get("toptags", {}).get("tag", [])
            results = []
            for t in tags[:limit]:
                results.append({
                    "name": t.get("name", "").lower(),
                    "count": int(t.get("count", 0)),
                })
            return results
        except Exception:
            return []
    
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
        
        Note: Uses normalized artist names for comparison to handle case/accent variations.
        """
        if not self.api_key:
            return []
        
        # Normalize existing artists for comparison
        existing_normalized = {normalize_artist_name(a) for a in existing_artists}
        seed_normalized = {normalize_artist_name(s) for s in seed_artists}
        
        candidates = {}
        
        for seed in seed_artists:
            similar = self.get_similar_artists(seed, limit=15, min_match=min_match)
            
            for artist in similar:
                name = artist["name"]
                name_normalized = normalize_artist_name(name)
                
                # Skip if already exists (case/accent insensitive)
                if name_normalized in existing_normalized or name_normalized in seed_normalized:
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


def get_genre_from_audiodb(artist_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch artist genre from TheAudioDB and map to dataset genre.
    
    Uses scored matching that prefers:
    1. Style over genre (more specific)
    2. Exact matches over partial matches
    
    Returns:
        Tuple of (mapped_genre, raw_genre, raw_style) for debugging/inspection.
    """
    try:
        url = f"{AUDIODB_URL}/search.php"
        r = requests.get(url, params={"s": artist_name}, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        artists = data.get("artists")
        if not artists:
            return None, None, None
        
        artist = artists[0]
        genre = artist.get("strGenre", "").lower().strip()
        style = artist.get("strStyle", "").lower().strip()
        
        # Score matches - prefer style (more specific) over genre
        best_genre = None
        best_score = 0.0
        
        for term, base_weight in [(style, 1.0), (genre, 0.8)]:
            if not term:
                continue
            
            # Exact match
            if term in AUDIODB_GENRE_MAP:
                score = 1.0 * base_weight
                if score > best_score:
                    best_genre = AUDIODB_GENRE_MAP[term]
                    best_score = score
                continue
            
            # Partial match
            for key, value in AUDIODB_GENRE_MAP.items():
                if key in term or term in key:
                    score = 0.6 * base_weight
                    if score > best_score:
                        best_genre = value
                        best_score = score
        
        return best_genre, genre, style
    except Exception:
        return None, None, None


def _score_genre_match(tag_name: str, tag_count: int, max_count: int) -> Tuple[Optional[str], float]:
    """Score a genre match based on tag name and count.
    
    Returns (mapped_genre, score) where score is 0-1.
    Score is based on:
    - Match type: exact (1.0), key-in-tag (0.7), tag-in-key (0.5)
    - Tag popularity: weighted by count relative to max_count
    """
    # Normalize score by popularity (0.3 to 1.0 range to avoid zero)
    popularity = 0.3 + 0.7 * (tag_count / max_count) if max_count > 0 else 0.5
    
    # Exact match
    if tag_name in AUDIODB_GENRE_MAP:
        return AUDIODB_GENRE_MAP[tag_name], 1.0 * popularity
    
    # Partial matches - key substring in tag
    for key, value in AUDIODB_GENRE_MAP.items():
        if key in tag_name:
            return value, 0.7 * popularity
    
    # Partial matches - tag substring in key
    for key, value in AUDIODB_GENRE_MAP.items():
        if tag_name in key:
            return value, 0.5 * popularity
    
    return None, 0.0


def get_genre_from_lastfm(artist_name: str, lastfm_client: Optional[LastFmClient] = None) -> Tuple[Optional[str], List[str]]:
    """Fetch artist genre from Last.fm tags with weighted scoring.
    
    Uses a scoring system that considers:
    - Exact vs partial matches
    - Tag popularity (count)
    
    Returns:
        Tuple of (mapped_genre, raw_tags_list) for debugging/inspection.
    """
    if lastfm_client is None:
        lastfm_client = LastFmClient()
    
    if not lastfm_client.api_key:
        return None, []
    
    tags = lastfm_client.get_artist_tags(artist_name, limit=10)
    raw_tags = [t["name"] for t in tags]
    
    if not tags:
        return None, []
    
    # Get max count for normalization
    max_count = max(t["count"] for t in tags)
    
    # Score all tags and pick the best match
    best_genre = None
    best_score = 0.0
    
    for tag in tags:
        genre, score = _score_genre_match(tag["name"], tag["count"], max_count)
        if genre and score > best_score:
            best_genre = genre
            best_score = score
    
    return best_genre, raw_tags


def get_cached_genre(artist_name: str) -> Optional[str]:
    """Get genre with caching to minimize API calls.
    
    Tries Last.fm tags first (more reliable), then falls back to TheAudioDB.
    """
    if artist_name not in _genre_cache:
        # Try Last.fm first (better tags)
        genre, _ = get_genre_from_lastfm(artist_name)
        if genre:
            _genre_cache[artist_name] = genre
        else:
            # Fall back to TheAudioDB
            genre, _, _ = get_genre_from_audiodb(artist_name)
            _genre_cache[artist_name] = genre
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
            
            time.sleep(RATE_LIMIT_SONGLINK) 
        
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
) -> pl.DataFrame:
    """Build Polars DataFrame from API responses with RAW (unscaled) values."""
    rows = []
    
    if verbose and tracks:
        print(f"      Tracks: {', '.join(t.get('trackTitle', '?') for t in tracks[:5])}" + 
              (f" (+{len(tracks)-5} more)" if len(tracks) > 5 else ""))
    
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
            "popularity": float(track.get("popularity")) if track.get("popularity") is not None else None,
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
            "duration_ms": float(track.get("durationMs")) if track.get("durationMs") is not None else None,
            "time_signature": feat.get("time_signature"),
        })

    if not rows:
        return pl.DataFrame(schema=RAW_SCHEMA)
    
    df = pl.from_dicts(rows)
    
    # Ensure all RAW_COLS exist
    for col in RAW_COLS:
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).alias(col))
    
    # Coerce types and select in canonical order
    df = coerce_to_schema(df)
    return df.select(RAW_COLS)


def weighted_track_sample(
    tracks: List[Dict],
    features: Dict[str, Dict],
    target_count: int,
    diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
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


def _normalize_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize DataFrame schema for safe concatenation.
    
    Uses schema.py's normalize_for_merge() for consistent type coercion.
    
    - Removes pandas index artifacts (Unnamed: 0)
    - Coerces types to canonical RAW_SCHEMA (Int64 for integers, Float64 for floats)
    - Selects only RAW_COLUMN_ORDER columns
    """
    df = normalize_for_merge(df)
    
    # Select only columns we care about (in canonical order)
    cols_to_keep = [c for c in RAW_COLUMN_ORDER if c in df.columns]
    df = df.select(cols_to_keep)
    
    return df


def load_existing() -> Tuple[pl.DataFrame, pl.DataFrame]:
    """Load both main dataset and added_artists parquet files if they exist.
    
    Returns DataFrames with normalized schemas (same columns/types) for safe concatenation.
    """
    # Use RAW_SCHEMA from schema.py for consistent types
    df_main = pl.DataFrame(schema=RAW_SCHEMA)
    df_added = pl.DataFrame(schema=RAW_SCHEMA)
    
    if MAIN_DATASET.exists():
        df_main = pl.read_parquet(MAIN_DATASET)
        df_main = _normalize_schema(df_main)
    
    if OUTPUT_PARQUET.exists():
        df_added = pl.read_parquet(OUTPUT_PARQUET)
        df_added = _normalize_schema(df_added)
    elif LEGACY_CSV.exists():
        # Backward compat: read legacy CSV if parquet doesn't exist
        import zipfile
        with zipfile.ZipFile(LEGACY_CSV, 'r') as zf:
            csv_names = [n for n in zf.namelist() if n.endswith('.csv')]
            if csv_names:
                with zf.open(csv_names[0]) as f:
                    df_added = pl.read_csv(f, infer_schema_length=10000)
        df_added = _normalize_schema(df_added)
    
    # If one is empty, match its schema to the other
    if len(df_main) == 0 and len(df_added) > 0:
        df_main = pl.DataFrame(schema={c: df_added[c].dtype for c in df_added.columns})
    elif len(df_added) == 0 and len(df_main) > 0:
        df_added = pl.DataFrame(schema={c: df_main[c].dtype for c in df_main.columns})
    
    return df_main, df_added


def save_parquet(df: pl.DataFrame) -> None:
    """Save DataFrame to parquet (primary format)."""
    df.write_parquet(OUTPUT_PARQUET, compression="zstd", compression_level=12)


def save_csv_zip(df: pl.DataFrame) -> None:
    """Save DataFrame to compressed CSV zip (legacy, for backward compat)."""
    csv_buffer = io.StringIO()
    df.write_csv(csv_buffer)
    
    with zipfile.ZipFile(LEGACY_CSV, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("added_artists.csv", csv_buffer.getvalue())


def deduplicate_with_report(
    df_combined: pl.DataFrame, 
    df_main: pl.DataFrame,
) -> Tuple[pl.DataFrame, List[str]]:
    """Deduplicate and return removed track names for reporting."""
    removed_tracks = []
    
    main_track_ids = set(df_main["track_id"].drop_nulls().unique().to_list()) if len(df_main) > 0 else set()
    
    # Find tracks already in main
    in_main = df_combined.filter(pl.col("track_id").is_in(list(main_track_ids)))
    for row in in_main.iter_rows(named=True):
        removed_tracks.append(f"  - {row['artist_name']} - {row['track_name']} (already in dataset)")
    
    df_combined = df_combined.filter(~pl.col("track_id").is_in(list(main_track_ids)))
    
    before = len(df_combined)
    df_combined = deduplicate_tracks_polars(df_combined)
    n_removed = before - len(df_combined)
    if n_removed > 0:
        removed_tracks.append(f"  + {n_removed} similar track names removed")
    
    return df_combined, removed_tracks


@dataclass(frozen=True)
class ArtistSearchResult:
    """Result of artist search with source attribution."""
    name: str                                      # Confirmed/canonical name
    recco_uuid: str                                # ReccoBeats artist UUID
    source: Literal["reccobeats", "deezer_fallback"]


def search_artist(
    name: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    *,
    client: Optional["ReccoBeatsClient"] = None,
    quiet: bool = True,
    verbose: bool = False,
) -> Optional[ArtistSearchResult]:
    """Unified artist search: ReccoBeats direct search, then Deezer fallback.
    
    This is the canonical search function. All discovery scripts should use this
    or functions that call it (like add_discovered_artist).
    
    Args:
        name: Artist name to search for
        limit: Max results from ReccoBeats search (default 20, API can return up to 1000)
        client: Optional ReccoBeatsClient instance (created if not provided)
        quiet: Suppress output
        verbose: Print extra details
        
    Returns:
        ArtistSearchResult with recco_uuid and confirmed name, or None if not found
    """
    client = client or ReccoBeatsClient()
    target_norm = normalize_artist_name(name)
    
    # 1) Try ReccoBeats direct search first - ONLY use exact match
    try:
        candidates = client.search_artist(name, limit=limit)
        if candidates:
            # Only use ReccoBeats if we have an exact normalized match
            best = None
            for c in candidates:
                if normalize_artist_name(c.get("name", "")) == target_norm:
                    best = c
                    break
            
            if best:
                recco_uuid = best.get("id")
                confirmed = best.get("name") or name
                
                if recco_uuid:
                    if verbose and not quiet:
                        print(f"    Found: {confirmed} (ReccoBeats)")
                    return ArtistSearchResult(name=confirmed, recco_uuid=recco_uuid, source="reccobeats")
    except Exception as e:
        if verbose and not quiet:
            print(f"    ReccoBeats search failed: {e}")
    
    # 2) Fallback: Deezer → Songlink → Spotify track → ReccoBeats artist
    spotify_track_id = search_artist_via_deezer(name, verbose=verbose, quiet=quiet)
    if not spotify_track_id:
        if not quiet:
            print(f"    Not found on ReccoBeats or Deezer")
        return None
    
    tracks = client.get_tracks([spotify_track_id])
    if not tracks:
        return None
    
    artists = (tracks[0] or {}).get("artists") or []
    if not artists:
        return None
    
    # Extract Spotify artist ID from href, then look up ReccoBeats UUID
    href = artists[0].get("href", "")
    spotify_artist_id = href.split("/")[-1] if href else None
    
    if not spotify_artist_id:
        return None
    
    # Convert Spotify artist ID to ReccoBeats UUID via /artist?ids= endpoint
    result = client.get_artist_from_spotify_id(spotify_artist_id)
    if not result:
        if not quiet:
            print(f"    Could not resolve ReccoBeats UUID for Spotify artist")
        return None
    
    recco_uuid, confirmed = result
    
    if verbose and not quiet:
        print(f"    Found: {confirmed} (Deezer fallback)")
    
    return ArtistSearchResult(name=confirmed, recco_uuid=recco_uuid, source="deezer_fallback")


def search_artist_via_reccobeats(
    artist_name: str, 
    limit: int = DEFAULT_SEARCH_LIMIT,
    verbose: bool = False, 
    quiet: bool = False
) -> Optional[Tuple[str, str]]:
    """Search for artist via ReccoBeats only (no Deezer fallback).
    
    DEPRECATED: Prefer search_artist() for full fallback handling.
    
    Args:
        artist_name: Artist to search for
        limit: Max search results (default 20)
        verbose: Print extra details
        quiet: Suppress output
        
    Returns:
        Tuple of (recco_artist_uuid, confirmed_name) or None if not found
    """
    result = search_artist(artist_name, limit=limit, quiet=quiet, verbose=verbose)
    if result and result.source == "reccobeats":
        return (result.recco_uuid, result.name)
    # If only ReccoBeats search failed but Deezer worked, still return None
    # to preserve original "ReccoBeats only" behavior
    if result and result.source == "deezer_fallback":
        return None
    return None


def add_discovered_artist(
    artist_name: str,
    existing_track_ids: Set[str],
    skip_unknown: bool = True,
    use_infer: bool = False,
    tracks_per_artist: int = DEFAULT_TRACKS_PER_ARTIST,
    diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
    verbose: bool = False,
    quiet: bool = False,
    lastfm_client: Optional["LastFmClient"] = None,
    use_deezer_fallback: bool = True,
) -> Optional[pl.DataFrame]:
    """Fetch and add tracks for a discovered artist.
    
    This is the canonical function for the full artist→tracks pipeline.
    Uses search_artist() for unified ReccoBeats → Deezer fallback.
    
    Returns DataFrame of new tracks, or None if artist should be skipped.
    """
    client = ReccoBeatsClient()
    
    # Use unified search_artist() which handles ReccoBeats → Deezer fallback internally
    if use_deezer_fallback:
        result = search_artist(artist_name, client=client, quiet=quiet, verbose=verbose)
    else:
        # ReccoBeats only - use the legacy wrapper that filters to reccobeats source
        rb_result = search_artist_via_reccobeats(artist_name, verbose=verbose, quiet=quiet)
        result = ArtistSearchResult(name=rb_result[1], recco_uuid=rb_result[0], source="reccobeats") if rb_result else None
    
    if not result:
        if verbose:
            print(f"    Search returned no result")
        return None

    artist_uuid = result.recco_uuid
    confirmed_name = result.name

    if verbose:
        print(f"    Search found: {confirmed_name} (uuid: {artist_uuid[:8]}...)")

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
    if verbose:
        print(f"    ReccoBeats has {len(artist_tracks)} tracks for this artist")
    if not artist_tracks:
        if verbose:
            print(f"    No tracks found")
        return None

    new_tracks = [
        t for t in artist_tracks
        if t.get("href", "").split("/")[-1] not in existing_track_ids
    ]
    if verbose:
        existing_count = len(artist_tracks) - len(new_tracks)
        if existing_count > 0:
            print(f"    Filtered {existing_count} tracks already in dataset, {len(new_tracks)} new tracks remain")

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
    df_new = deduplicate_tracks_polars(df_new)
    
    return df_new


def get_artist_unique_count(
    df_all: pl.DataFrame,
    artist_name: str,
) -> int:
    """Get the number of unique tracks for an artist after deduplication.
    
    Uses normalize_artist_name() for case/accent-insensitive matching.
    """
    target_norm = normalize_artist_name(artist_name)
    
    df_artist = df_all.filter(
        pl.col("artist_name").map_elements(
            normalize_artist_name, return_dtype=pl.String
        ) == target_norm
    )
    
    if df_artist.is_empty():
        return 0
    
    df_deduped = deduplicate_tracks_polars(df_artist)
    return len(df_deduped)


def backfill_artist_quota(
    *,
    client: "ReccoBeatsClient",
    artist_name: str,
    recco_uuid: str,
    genre: str,
    df_main: pl.DataFrame,
    df_added: pl.DataFrame,
    existing_track_ids: Set[str],
    target_track_count: int = DEFAULT_TRACKS_PER_ARTIST,
    diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
    verbose: bool = False,
) -> Tuple[pl.DataFrame, int]:
    """Backfill an artist to quota using the CHEAP top tracks endpoint.
    
    This uses get_artist_tracks() (1-2 API calls) instead of scanning every album.
    Use this for --backfill-partial in check_trending.py.
    
    For full album scanning (e.g., check_new_albums.py --update), use add_tracks_for_artist().
    
    Args:
        client: ReccoBeatsClient instance (reused for caching)
        artist_name: Canonical artist name
        recco_uuid: ReccoBeats artist UUID  
        genre: Genre to assign to tracks
        df_main: Main dataset DataFrame
        df_added: Added artists DataFrame
        existing_track_ids: Set of track IDs already in dataset
        target_track_count: Target number of unique tracks for artist
        diversity_weight: Weight for diversity vs popularity in sampling
        verbose: Print progress
        
    Returns:
        Tuple of (updated df_added, number of tracks added)
    """
    df_all = pl.concat([df_main, df_added])
    
    existing_count = get_artist_unique_count(df_all, artist_name)
    needed = max(0, target_track_count - existing_count)
    
    if verbose:
        print(f"    Existing: {existing_count}, target: {target_track_count}, needed: {needed}")
    
    if needed == 0:
        if verbose:
            print(f"    Already at quota")
        return df_added, 0
    
    # Use cheap top tracks endpoint (1-2 paginated calls)
    fetch_limit = needed * 3  # Fetch extra to account for dedup/filtering
    artist_tracks = client.get_artist_tracks(recco_uuid, fetch_limit)
    
    if not artist_tracks:
        if verbose:
            print(f"    No tracks found via top tracks endpoint")
        return df_added, 0
    
    # Filter out tracks already in dataset
    new_tracks = [
        t for t in artist_tracks
        if t.get("href", "").split("/")[-1] not in existing_track_ids
    ]
    
    if verbose:
        existing_filtered = len(artist_tracks) - len(new_tracks)
        if existing_filtered > 0:
            print(f"    Filtered {existing_filtered} tracks already in dataset, {len(new_tracks)} remain")
    
    if not new_tracks:
        if verbose:
            print(f"    All top tracks already in dataset")
        return df_added, 0
    
    # Get audio features for sampling
    spotify_ids = [t.get("href", "").split("/")[-1] for t in new_tracks if t.get("href")]
    features = client.get_audio_features(spotify_ids)
    
    # Sample using weighted_track_sample (popularity + diversity)
    sampled = weighted_track_sample(
        new_tracks,
        features,
        target_count=needed,
        diversity_weight=diversity_weight,
    )
    
    # Build rows and deduplicate
    df_new = build_rows(artist_name, sampled, features, genre, verbose)
    df_new = deduplicate_tracks_polars(df_new)
    
    # Remove tracks already in main dataset
    if len(df_main) > 0:
        main_track_ids = set(df_main["track_id"].drop_nulls().unique().to_list())
        df_new = df_new.filter(~pl.col("track_id").is_in(list(main_track_ids)))
    
    # Limit to needed count
    if len(df_new) > needed:
        df_new = df_new.head(needed)
    
    added_count = len(df_new)
    
    if added_count > 0:
        df_added = normalize_for_merge(df_added)
        df_new = normalize_for_merge(df_new)
        df_added = pl.concat([df_added, df_new])
        
        # Update existing_track_ids
        for tid in df_new["track_id"].drop_nulls().to_list():
            existing_track_ids.add(tid)
    
    return df_added, added_count


def add_tracks_for_artist(
    *,
    client: "ReccoBeatsClient",
    artist_name: str,
    recco_uuid: str,
    genre: str,
    df_main: pl.DataFrame,
    df_added: pl.DataFrame,
    existing_track_ids: Set[str],
    target_track_count: int = DEFAULT_TRACKS_PER_ARTIST,
    include_singles: bool = False,
    keep_all: bool = False,
    skip_variants: bool = True,
    diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
    verbose: bool = False,
) -> Tuple[pl.DataFrame, int]:
    """Add tracks for an artist up to a target quota (after deduplication).
    
    This is the unified function for backfilling/updating artist tracks.
    It ensures the artist ends up with `target_track_count` unique tracks
    by adding only as many new tracks as needed.
    
    Args:
        client: ReccoBeatsClient instance (reused for caching)
        artist_name: Canonical artist name
        recco_uuid: ReccoBeats artist UUID  
        genre: Genre to assign to tracks
        df_main: Main dataset DataFrame
        df_added: Added artists DataFrame
        existing_track_ids: Set of track IDs already in dataset
        target_track_count: Target number of unique tracks for artist
        include_singles: Include singles in candidate albums
        keep_all: If True, add ALL tracks from albums (ignore sampling)
        skip_variants: Skip remix/acoustic/live album variants
        diversity_weight: Weight for diversity vs popularity in sampling
        verbose: Print progress
        
    Returns:
        Tuple of (updated df_added, number of tracks added)
    """
    df_all = pl.concat([df_main, df_added])
    
    # Calculate how many tracks needed
    existing_count = get_artist_unique_count(df_all, artist_name)
    needed = max(0, target_track_count - existing_count)
    
    if verbose:
        print(f"    Existing: {existing_count}, target: {target_track_count}, needed: {needed}")
    
    if needed == 0 and not keep_all:
        if verbose:
            print(f"    Already at quota")
        return df_added, 0
    
    # Get all albums for artist
    albums = client.get_artist_albums(recco_uuid)
    if not albums:
        return df_added, 0
    
    # Filter albums
    candidate_albums = []
    for album in albums:
        album_type = album.get("type", "").lower()
        album_name = album.get("name", "")
        
        # Skip singles unless requested
        if not include_singles and album_type == "single":
            continue
        
        # Skip variant albums (remix/acoustic/live) if requested
        if skip_variants:
            import re
            skip_patterns = [
                r'\bremix(es)?\b', r'\bacoustic\s*(version|collection)?\b',
                r'\blive\s*(at|from|in|version)?\b', r'\bremaster(ed)?\b',
                r'\bkaraoke\b', r'\binstrumental\s*version\b',
                r'\btrack\s*by\s*track\b',
            ]
            skip_re = re.compile('|'.join(skip_patterns), re.IGNORECASE)
            if skip_re.search(album_name):
                continue
        
        candidate_albums.append(album)
    
    if not candidate_albums:
        if verbose:
            print(f"    No candidate albums after filtering")
        return df_added, 0
    
    # Collect tracks from candidate albums
    all_tracks = []
    for album in candidate_albums:
        album_uuid = album.get("id")
        if not album_uuid:
            continue
        
        tracks = client.get_album_tracks(album_uuid)
        for t in tracks:
            href = t.get("href", "")
            tid = href.split("/")[-1] if href else None
            if tid and tid not in existing_track_ids:
                all_tracks.append(t)
    
    if not all_tracks:
        if verbose:
            print(f"    No new tracks found in albums")
        return df_added, 0
    
    if verbose:
        print(f"    Found {len(all_tracks)} candidate tracks from {len(candidate_albums)} albums")
    
    # Get audio features for sampling
    spotify_ids = list({t.get("href", "").split("/")[-1] for t in all_tracks if t.get("href")})
    
    # Cap features fetch to avoid excessive API calls
    max_features = min(len(spotify_ids), max(needed * 8, 100))
    features = client.get_audio_features(spotify_ids[:max_features])
    
    # Sample or keep all
    if keep_all:
        sampled = all_tracks
    else:
        # Sample enough to reach quota after deduplication
        # Fetch extra to account for dedup losses
        sample_target = min(len(all_tracks), needed * 2)
        sampled = weighted_track_sample(
            all_tracks,
            features,
            target_count=sample_target,
            diversity_weight=diversity_weight,
        )
    
    # Build rows
    df_new = build_rows(artist_name, sampled, features, genre, verbose)
    
    # Deduplicate within new tracks
    df_new = deduplicate_tracks_polars(df_new)
    
    # Remove tracks already in main dataset
    if len(df_main) > 0:
        main_track_ids = set(df_main["track_id"].drop_nulls().unique().to_list())
        df_new = df_new.filter(~pl.col("track_id").is_in(list(main_track_ids)))
    
    # Limit to needed count (quota)
    if not keep_all and len(df_new) > needed:
        df_new = df_new.head(needed)
    
    added_count = len(df_new)
    
    if added_count > 0:
        df_added = normalize_for_merge(df_added)
        df_new = normalize_for_merge(df_new)
        df_added = pl.concat([df_added, df_new])
        
        # Update existing_track_ids
        for tid in df_new["track_id"].drop_nulls().to_list():
            existing_track_ids.add(tid)
    
    return df_added, added_count
