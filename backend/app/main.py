"""
FastAPI backend for Vibe music recommendation app.
"""

import json
import secrets
import os
import hashlib
from time import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from collections import Counter, deque


from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


from logic import MusicData, ParquetDataSource, generate_recommendations, GENRE_FOCUS, TRACKS_PER_ARTIST, VARIETY, MAX_ARTISTS

# Data path - configurable via environment in production
DATA_PATH = Path(__file__).parent.parent / "data" / "data_encoded.parquet"
ANALYTICS_PATH = Path(__file__).parent.parent / "data" / "analytics.jsonl"

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

# Security
security = HTTPBasic()

def get_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Check basic auth credentials."""
    correct_username = secrets.compare_digest(credentials.username, "admin")
    password = os.getenv("ANALYTICS_PASSWORD", "admin")
    correct_password = secrets.compare_digest(credentials.password, password)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username



class RecommendRequest(BaseModel):
    artists: list[str]
    track_ids: list[str] | None = None
    exclude_artists: list[str] | None = None
    diversity: int = VARIETY
    max_artists: int = MAX_ARTISTS
    genre_weight: int = GENRE_FOCUS
    tracks_per_artist: int = TRACKS_PER_ARTIST
    vibe_mood: float = 0.0  # -1 (chill) to +1 (energetic)
    vibe_sound: float = 0.0  # -1 (acoustic) to +1 (electronic)
    popularity: float = 0.0  # -1 (hidden gems) to +1 (mainstream)
    # Debug flags
    debug: bool = False
    debug_audio: bool = False
    # Client ID for analytics deduplication
    client_id: str | None = Field(default=None, max_length=64)


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


class AnalyticsEvent(BaseModel):
    """Generic event for tracking user interactions."""
    event_type: str  # e.g., "add_favorite", "remove_favorite", "add_known", "remove_known", "play_track"
    client_id: str | None = None
    payload: dict = {}  # Event-specific data (track info, artist name, etc.)


def log_event_async(event_data: dict):
    """Append event to analytics JSONL file (background task)."""
    try:
        with open(ANALYTICS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_data) + "\n")
    except Exception as e:
        print(f"Failed to log event: {e}")


def log_search_async(log_data: dict):
    """Append search log to JSONL file (background task)."""
    try:
        with open(ANALYTICS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data) + "\n")
    except Exception as e:
        print(f"Failed to log search: {e}")


# Analytics rate limiting / deduplication
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
async def get_artists(q: str = "", limit: int = 1000) -> list[str]:
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
            "track_ids": request.track_ids, # Explicitly save input track IDs
            "exclude_artists": valid_exclude,
            "settings": {
                "diversity": request.diversity,
                "max_artists": request.max_artists,
                "genre_weight": request.genre_weight,
                "tracks_per_artist": request.tracks_per_artist,
                "vibe_mood": request.vibe_mood,
                "vibe_sound": request.vibe_sound,
                "popularity": request.popularity,
            },
            "results": {
                artist: [{"id": t["track_id"], "name": t["track_name"]} for t in tracks]
                for artist, tracks in recs.items()
            },
            "result_count": len(recs),
            "client_id": request.client_id,
        }
        background_tasks.add_task(log_search_async, log_data)
    
    return RecommendResponse(recommendations=recs, meta=meta)


@app.get("/artists/{artist_name:path}/tracks")
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
    
    return [
        Track(track_id=row['track_id'], track_name=row['track_name'])
        for row in artist_tracks.select(['track_id', 'track_name']).iter_rows(named=True)
    ]


@app.post("/log/action")
async def track_event(event: AnalyticsEvent, background_tasks: BackgroundTasks):
    """Track a user interaction event (favorites, known artists, plays)."""
    event_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event.event_type,
        "client_id": event.client_id,
        **event.payload,
    }
    background_tasks.add_task(log_event_async, event_data)
    return {"status": "ok"}


@app.get("/analytics/stats")
async def get_analytics_stats(username: str = Depends(get_admin)):
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


@app.get("/analytics/dashboard", response_class=HTMLResponse)
async def analytics_dashboard(username: str = Depends(get_admin)):
    """Serve the simple analytics dashboard (Protected)."""
    try:
        dashboard_path = Path(__file__).parent.parent / "dashboard.html"
        if not dashboard_path.exists():
            return "Dashboard template not found"
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<html><body><h1>Dashboard temporarily unavailable</h1><p>{e}</p></body></html>"

@app.get("/analytics/data")
async def analytics_data(username: str = Depends(get_admin)):
    """Aggregate data for the dashboard (Protected)."""
    empty_response = {
        "total_searches": 0, 
        "daily_activity": {}, 
        "top_artists": [], 
        "vibe_stats": {}, 
        "top_tracks": [],
        "recent_searches": [],
        "vibe_scatter": [],
        "session_stats": {"avg_per_user": 0},
        "events": {"total": 0, "by_type": {}, "recent": [], "top_favorited_tracks": [], "top_known_artists": []},
    }
    
    if not ANALYTICS_PATH.exists():
        return empty_response
    
    # Global aggregates (O(1) memory accumulation)
    total_searches = 0
    unique_users = set()
    daily_activity = Counter()
    artist_counts = Counter()
    track_counts = Counter()
    
    # Event tracking
    event_counts = Counter()
    favorited_tracks = Counter()
    known_artists = Counter()
    recent_events = deque(maxlen=200)
    
    # Vibe lists for histograms
    vibe_moods = []
    vibe_sounds = []
    popularities = []
    vibe_scatter = []

    # Keep only the last 500 search entries
    recent_entries = deque(maxlen=500)

    try:
        with open(ANALYTICS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    entry = json.loads(line)
                    
                    event_type = entry.get("event_type")
                    
                    # Handle user interaction events
                    if event_type:
                        event_counts[event_type] += 1
                        recent_events.append(entry)
                        
                        if cid := entry.get("client_id"):
                            unique_users.add(cid)
                        
                        # Track favorited tracks/artists
                        if event_type == "add_favorite":
                            track_key = f"{entry.get('track_name', '?')} - {entry.get('artist_name', '?')}"
                            favorited_tracks[track_key] += 1
                        elif event_type == "add_known":
                            known_artists[entry.get("artist_name", "?")] += 1
                        
                        ts = entry.get("timestamp", "")[:10]
                        if ts:
                            daily_activity[ts] += 1
                        continue
                    
                    # Handle search entries (no event_type = legacy search format)
                    total_searches += 1
                    
                    if cid := entry.get("client_id"):
                        unique_users.add(cid)
                        
                    ts = entry.get("timestamp", "")[:10]
                    if ts:
                        daily_activity[ts] += 1
                        
                    for artist in entry.get("input_artists", []):
                        artist_counts[artist] += 1
                    
                    settings = entry.get("settings", {})
                    mood = settings.get("vibe_mood", 0)
                    sound = settings.get("vibe_sound", 0)
                    pop = settings.get("popularity", 0)
                    
                    vibe_moods.append(mood)
                    vibe_sounds.append(sound)
                    popularities.append(pop)
                    
                    if mood != 0 or sound != 0:
                        vibe_scatter.append({"x": mood, "y": sound})

                    results = entry.get("results")
                    if isinstance(results, dict):
                        for artist, tracks in results.items():
                            for t in tracks:
                                if isinstance(t, dict) and "name" in t:
                                    track_counts[f"{t['name']} - {artist}"] += 1

                    recent_entries.append(entry)
                        
                except json.JSONDecodeError:
                    continue
        
        # Format recent searches
        recent_searches = []
        for entry in reversed(recent_entries):
            raw_results = entry.get("results", {})
            recent_searches.append({
                "timestamp": entry.get("timestamp"),
                "client_id": entry.get("client_id"),
                "inputs": entry.get("input_artists"),
                "input_tracks": entry.get("track_ids"),
                "vibes": {
                    "mood": entry.get("settings", {}).get("vibe_mood", 0),
                    "sound": entry.get("settings", {}).get("vibe_sound", 0),
                    "pop": entry.get("settings", {}).get("popularity", 0),
                },
                "results": raw_results
            })
        
        # Format recent events
        formatted_events = []
        for evt in reversed(recent_events):
            formatted_events.append({
                "timestamp": evt.get("timestamp"),
                "client_id": evt.get("client_id"),
                "event_type": evt.get("event_type"),
                "track_id": evt.get("track_id"),
                "track_name": evt.get("track_name"),
                "artist_name": evt.get("artist_name"),
            })
            
        avg_searches = 0
        if unique_users:
            avg_searches = round(total_searches / len(unique_users), 1)

        return {
            "total_searches": total_searches,
            "unique_users": len(unique_users),
            "session_stats": {"avg_per_user": avg_searches},
            "daily_activity": dict(sorted(daily_activity.items())),
            "top_artists": artist_counts.most_common(20),
            "top_tracks": track_counts.most_common(20),
            "vibe_stats": {
                "mood": vibe_moods,
                "sound": vibe_sounds,
                "popularity": popularities
            },
            "vibe_scatter": vibe_scatter, 
            "recent_searches": recent_searches,
            "events": {
                "total": sum(event_counts.values()),
                "by_type": dict(event_counts),
                "recent": formatted_events,
                "top_favorited_tracks": favorited_tracks.most_common(20),
                "top_known_artists": known_artists.most_common(20),
            },
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
