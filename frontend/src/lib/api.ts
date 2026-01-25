const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface Track {
    track_id: string;
    track_name: string;
}

export interface RecommendRequest {
    artists: string[];
    track_ids?: string[];
    exclude_artists?: string[];
    diversity?: number;
    max_artists?: number;
    genre_weight?: number;
    tracks_per_artist?: number;
    vibe_mood?: number;  // -1 (chill) to +1 (energetic)
    vibe_sound?: number; // -1 (acoustic) to +1 (electronic)
    popularity?: number; // -1 (hidden gems) to +1 (mainstream)
}

export interface RecommendResponse {
    recommendations: Record<string, Track[]>;
}

export async function fetchArtists(query = '', limit = 100): Promise<string[]> {
    const params = new URLSearchParams();
    if (query) params.set('q', query);
    params.set('limit', String(limit));

    const res = await fetch(`${API_BASE}/artists?${params}`);
    if (!res.ok) throw new Error('Failed to fetch artists');
    return res.json();
}

export async function fetchRecommendations(request: RecommendRequest): Promise<RecommendResponse> {
    const res = await fetch(`${API_BASE}/recommend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || 'Failed to get recommendations');
    }

    return res.json();
}

export async function fetchArtistTracks(artistName: string): Promise<Track[]> {
    const res = await fetch(`${API_BASE}/artists/${encodeURIComponent(artistName)}/tracks`);
    if (!res.ok) throw new Error('Failed to fetch tracks');
    return res.json();
}
