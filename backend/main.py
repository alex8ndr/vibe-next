"""
FastAPI backend for Vibe music recommendation app.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from logic import MusicData, ParquetDataSource, generate_recommendations

# Data path - configurable via environment in production
DATA_PATH = Path(__file__).parent / "data" / "data_encoded.parquet"

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
    
    # Cleanup if needed
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
    diversity: int = 2
    max_artists: int = 6
    genre_weight: float = 2.0


class Track(BaseModel):
    track_id: str
    track_name: str
    year: int | None = None
    genre: str | None = None


class RecommendResponse(BaseModel):
    recommendations: dict[str, list[Track]]


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
async def recommend(request: RecommendRequest) -> RecommendResponse:
    """Generate music recommendations based on selected artists."""
    if not music_data:
        raise HTTPException(status_code=503, detail="Data not loaded")
    
    if not request.artists:
        raise HTTPException(status_code=400, detail="At least one artist required")
    
    # Validate artists exist
    valid_artists = [a for a in request.artists if a in music_data.artists_list]
    if not valid_artists:
        raise HTTPException(status_code=400, detail="No valid artists found")
    
    recs = generate_recommendations(
        data=music_data,
        input_artists=valid_artists,
        track_ids=request.track_ids,
        diversity=request.diversity,
        max_artists=request.max_artists,
        genre_weight=request.genre_weight
    )
    
    return RecommendResponse(recommendations=recs)


@app.get("/artists/{artist_name}/tracks")
async def get_artist_tracks(artist_name: str) -> list[Track]:
    """Get all tracks for a specific artist (for fine-tuning)."""
    if not music_data:
        raise HTTPException(status_code=503, detail="Data not loaded")
    
    df = music_data.df
    artist_tracks = df[df['artist_name'] == artist_name][['track_id', 'track_name']]
    
    if artist_tracks.empty:
        raise HTTPException(status_code=404, detail="Artist not found")
    
    return [
        Track(track_id=row['track_id'], track_name=row['track_name'])
        for _, row in artist_tracks.drop_duplicates('track_name').iterrows()
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
