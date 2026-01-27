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


class Track(BaseModel):
    track_id: str
    track_name: str
    year: int | None = None
    genre: str | None = None


class RecommendResponse(BaseModel):
    recommendations: dict[str, list[Track]]


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
    
    recs = generate_recommendations(
        data=music_data,
        input_artists=valid_artists,
        track_ids=request.track_ids,
        exclude_artists=valid_exclude,
        diversity=request.diversity,
        max_artists=request.max_artists,
        genre_weight=request.genre_weight,
        tracks_per_artist=request.tracks_per_artist,
        vibe_modifiers=vibe_modifiers if vibe_modifiers else None,
        popularity=request.popularity
    )
    
    # Log search in background
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
        "result_count": len(recs)
    }
    background_tasks.add_task(log_search_async, log_data)
    
    return RecommendResponse(recommendations=recs)


@app.get("/artists/{artist_name}/tracks")
async def get_artist_tracks(artist_name: str) -> list[Track]:
    """Get all tracks for a specific artist (for fine-tuning)."""
    if not music_data:
        raise HTTPException(status_code=503, detail="Data not loaded")
    
    df = music_data.df
    artist_tracks = df.filter(df['artist_name'] == artist_name).select(['track_id', 'track_name'])
    
    if len(artist_tracks) == 0:
        raise HTTPException(status_code=404, detail="Artist not found")
    
    # Remove duplicates and convert to Track objects
    unique_tracks = artist_tracks.unique(subset=['track_name'])
    
    return [
        Track(track_id=row['track_id'], track_name=row['track_name'])
        for row in unique_tracks.iter_rows(named=True)
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
