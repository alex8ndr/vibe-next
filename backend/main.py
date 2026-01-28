"""
FastAPI backend for Vibe music recommendation app.
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from logic import MusicData, ParquetDataSource, generate_recommendations
from track_dedup import deduplicate_tracks

# Data path - configurable via environment in production
DATA_PATH = Path(__file__).parent / "data" / "data_encoded.parquet"
ANALYTICS_PATH = Path(__file__).parent / "data" / "analytics.jsonl"

# Global data container
music_data: MusicData | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load data once at startup, cleanup on shutdown."""
    global music_data
    
    if not DATA_PATH.exists():
        raise RuntimeError(f"Data file not found: {DATA_PATH}")
    
    source = ParquetDataSource(DATA_PATH)
    music_data = MusicData(source)
    music_data.load()
    
    print(f"Loaded {len(music_data.df):,} tracks, {len(music_data.artists_list):,} artists")
    
    yield
    
    music_data = None


app = FastAPI(
    title="Vibe API",
    description="Music recommendation engine",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RecommendRequest(BaseModel):
    artists: list[str]
    track_ids: list[str] | None = None
    exclude_artists: list[str] | None = None
    diversity: int = 2
    max_artists: int = 6
    genre_weight: float = 2.0
    tracks_per_artist: int = 4
    vibe_mood: float = 0.0  # -1 (chill) to +1 (energetic)
    vibe_sound: float = 0.0  # -1 (acoustic) to +1 (electronic)
    popularity: float = 0.0  # -1 (hidden gems) to +1 (mainstream)
    # Debug flags
    debug: bool = False
    debug_audio: bool = False
    # Client ID for analytics deduplication
    client_id: str | None = None


class Track(BaseModel):
    track_id: str
    track_name: str
    year: int | None = None
    genre: str | None = None
    audio_features: dict[str, float | str] | None = None


class RecommendResponse(BaseModel):
    recommendations: dict[str, list[Track]]
    meta: dict | None = None


class SearchLog(BaseModel):
    input_artists: list[str]
    track_ids: list[str] | None = None
    exclude_artists: list[str] | None = None
    settings: dict
    result_artists: list[str]
    result_count: int


def log_search_async(log_data: dict):
    """Append search log to JSONL file (background task)."""
    try:
        with open(ANALYTICS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data) + "\n")
    except Exception as e:
        print(f"Failed to log search: {e}")


# Analytics rate limiting / deduplication
import hashlib
from time import time

RECENT_SEARCHES: dict[str, tuple[float, str]] = {}  # client_key -> (timestamp, signature)
ANALYTICS_MIN_INTERVAL = 5.0  # seconds between logged searches from same client


def should_log_search(client_id: str | None, request: 'RecommendRequest', valid_artists: list[str], valid_exclude: list[str] | None) -> bool:
    """Check if this search should be logged (rate limit + dedupe)."""
    client_key = client_id or "anonymous"
    
    # Build signature of meaningful request parameters
    sig_payload = {
        "artists": sorted(valid_artists),
        "track_ids": sorted(request.track_ids or []),
        "exclude": sorted(valid_exclude or []),
        "diversity": request.diversity,
        "max_artists": request.max_artists,
        "genre_weight": request.genre_weight,
        "tracks_per_artist": request.tracks_per_artist,
        "vibe_mood": request.vibe_mood,
        "vibe_sound": request.vibe_sound,
        "popularity": request.popularity,
    }
    sig = hashlib.sha1(json.dumps(sig_payload, sort_keys=True).encode()).hexdigest()
    
    now = time()
    if client_key in RECENT_SEARCHES:
        last_time, last_sig = RECENT_SEARCHES[client_key]
        # Skip if same signature within interval
        if sig == last_sig and (now - last_time) < ANALYTICS_MIN_INTERVAL:
            return False
    
    RECENT_SEARCHES[client_key] = (now, sig)
    
    # Cleanup old entries periodically (keep only last 1000)
    if len(RECENT_SEARCHES) > 1000:
        sorted_items = sorted(RECENT_SEARCHES.items(), key=lambda x: x[1][0], reverse=True)
        RECENT_SEARCHES.clear()
        RECENT_SEARCHES.update(dict(sorted_items[:500]))
    
    return True


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "tracks_loaded": len(music_data.df) if music_data else 0}


@app.get("/artists")
async def get_artists(q: str = "", limit: int = 100) -> list[str]:
    """
    Get artist list, optionally filtered by search query.
    Returns artists sorted by popularity.
    """
    if not music_data:
        raise HTTPException(status_code=503, detail="Data not loaded")
    
    artists = music_data.artists_list
    
    if q:
        q_lower = q.lower()
        artists = [a for a in artists if q_lower in a.lower()]
    
    return artists[:limit]


@app.post("/recommend", response_model=RecommendResponse)
async def recommend(
    request: RecommendRequest, 
    background_tasks: BackgroundTasks
) -> RecommendResponse:
    """Generate music recommendations based on selected artists."""
    if not music_data:
        raise HTTPException(status_code=503, detail="Data not loaded")
    
    if not request.artists:
        raise HTTPException(status_code=400, detail="At least one artist required")
    
    # Validate artists exist
    valid_artists = [a for a in request.artists if a in music_data.artists_list]
    if not valid_artists:
        raise HTTPException(status_code=400, detail="No valid artists found")
    
    # Also validate exclude_artists if provided (just filter to valid ones)
    valid_exclude = None
    if request.exclude_artists:
        valid_exclude = [a for a in request.exclude_artists if a in music_data.artists_list]
    
    # Build vibe modifiers dict (only include non-zero values)
    vibe_modifiers = {}
    if request.vibe_mood != 0.0:
        vibe_modifiers['mood'] = request.vibe_mood
    if request.vibe_sound != 0.0:
        vibe_modifiers['sound'] = request.vibe_sound
    
    recs, meta = generate_recommendations(
        data=music_data,
        input_artists=valid_artists,
        track_ids=request.track_ids,
        exclude_artists=valid_exclude,
        diversity=request.diversity,
        max_artists=request.max_artists,
        genre_weight=request.genre_weight,
        tracks_per_artist=request.tracks_per_artist,
        vibe_modifiers=vibe_modifiers if vibe_modifiers else None,
        popularity=request.popularity,
        debug=request.debug,
        debug_audio=request.debug_audio,
    )
    
    # Log search in background (with rate limiting)
    if should_log_search(request.client_id, request, valid_artists, valid_exclude):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "input_artists": valid_artists,
            "track_ids": request.track_ids,
            "exclude_artists": valid_exclude,
            "settings": {
                "diversity": request.diversity,
                "max_artists": request.max_artists,
                "genre_weight": request.genre_weight,
                "tracks_per_artist": request.tracks_per_artist
            },
            "results": {
                artist: [t["track_id"] for t in tracks]
                for artist, tracks in recs.items()
            },
            "result_count": len(recs),
            "client_id": request.client_id,
        }
        background_tasks.add_task(log_search_async, log_data)
    
    return RecommendResponse(recommendations=recs, meta=meta)


@app.get("/artists/{artist_name}/tracks")
async def get_artist_tracks(artist_name: str) -> list[Track]:
    """Get all tracks for a specific artist (for fine-tuning)."""
    if not music_data:
        raise HTTPException(status_code=503, detail="Data not loaded")
    
    df = music_data.df
    artist_tracks = df.filter(df['artist_name'] == artist_name)
    
    if len(artist_tracks) == 0:
        raise HTTPException(status_code=404, detail="Artist not found")
    
    if 'popularity' in artist_tracks.columns:
        artist_tracks = artist_tracks.sort(['popularity', 'track_name'], descending=[True, False])
    else:
        artist_tracks = artist_tracks.sort('track_name')
    
    unique_tracks = deduplicate_tracks(artist_tracks, track_col='track_name')
    
    return [
        Track(track_id=row['track_id'], track_name=row['track_name'])
        for row in unique_tracks.select(['track_id', 'track_name']).iter_rows(named=True)
    ]


@app.get("/analytics/stats")
async def get_analytics_stats():
    """Get basic analytics stats (for dev/admin use)."""
    if not ANALYTICS_PATH.exists():
        return {"total_searches": 0, "unique_artists_searched": 0}
    
    try:
        total = 0
        artists = set()
        with open(ANALYTICS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    total += 1
                    data = json.loads(line)
                    artists.update(data.get("input_artists", []))
        
        return {
            "total_searches": total,
            "unique_artists_searched": len(artists)
        }
    except json.JSONDecodeError as e:
        return {"error": f"Invalid analytics data: {e}"}
    except OSError as e:
        return {"error": f"Unable to read analytics data: {e}"}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
