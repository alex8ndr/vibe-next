import { API_BASE } from './apiBase';

export interface Track {
    track_id: string;
    track_name: string;
    genre?: string;
    language?: string;
    audio_features?: Record<string, number | string>;
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
    debug?: boolean;
    debug_audio?: boolean;
    client_id?: string;
    target_language?: string;
    target_genre?: string;
}

export interface GenreInfo {
    genre: string;
    pct: number;
}

export interface LanguageInfo {
    language: string;
    pct: number;
}

export interface ArtistDebugInfo {
    genre_profile: GenreInfo[];
    language_profile?: LanguageInfo[];
    audio_features?: Record<string, number>;
}

export interface RecommendMeta {
    has_more_candidates: boolean;
    debug?: Record<string, ArtistDebugInfo>;
    input_genre_profile?: Array<{ artist: string; genres: GenreInfo[] }>;
    search_vector_audio?: Record<string, number>;
    search_vector_genre?: GenreInfo[];
}

export interface RecommendResponse {
    recommendations: Record<string, Track[]>;
    meta?: RecommendMeta;
}

export interface TrackAudioFeaturesResponse {
    audio_features: Record<string, Record<string, number>>;
}

export async function fetchArtists(query = '', limit = 100, signal?: AbortSignal): Promise<string[]> {
    const params = new URLSearchParams();
    if (query) params.set('q', query);
    params.set('limit', String(limit));

    const res = await fetch(`${API_BASE}/artists?${params}`, { signal });
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

// Baseline expected durations (ms) from local fast machine - used as starting ratios
const STAGE_BASELINES: Record<string, number> = {
    seeds: 1,
    prep: 36,
    audio: 10,
    genre: 4,
    lang: 12,
    rank: 12,
};
const BASELINE_TOTAL = Object.values(STAGE_BASELINES).reduce((a, b) => a + b, 0);

// Cumulative progress % each stage completion represents
const STAGE_PROGRESS: Record<string, number> = {};
{
    let cumulative = 0;
    for (const [stage, ms] of Object.entries(STAGE_BASELINES)) {
        cumulative += ms;
        STAGE_PROGRESS[stage] = (cumulative / BASELINE_TOTAL) * 95; // cap at 95%, done=100
    }
}

export async function fetchRecommendationsStream(
    request: RecommendRequest,
    onProgress: (progress: number) => void,
): Promise<RecommendResponse> {
    const res = await fetch(`${API_BASE}/recommend-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || 'Failed to get recommendations');
    }

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let result: RecommendResponse | null = null;
    let progress = 0;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = JSON.parse(line.slice(6));

            if (data.stage === 'done') {
                onProgress(100);
                result = {
                    recommendations: data.recommendations,
                    meta: data.meta,
                };
            } else {
                const stageProgress = STAGE_PROGRESS[data.stage] ?? progress;
                progress = Math.max(progress, stageProgress);
                onProgress(progress);
            }
        }
    }

    if (!result) {
        throw new Error('Stream ended without results');
    }
    return result;
}

export async function fetchStats(): Promise<{ track_count: number; artist_count: number }> {
    const res = await fetch(`${API_BASE}/stats`);
    if (!res.ok) throw new Error('Failed to fetch stats');
    return res.json();
}

export interface FilterOption {
    value: string;
    label: string;
    count: number;
}

export async function fetchFilters(): Promise<{ languages: FilterOption[]; genres: FilterOption[] }> {
    const res = await fetch(`${API_BASE}/filters`);
    if (!res.ok) throw new Error('Failed to fetch filters');
    return res.json();
}

export async function fetchArtistTracks(artistName: string): Promise<Track[]> {
    const res = await fetch(`${API_BASE}/artists/${encodeURIComponent(artistName)}/tracks`);
    if (!res.ok) throw new Error('Failed to fetch tracks');
    return res.json();
}

export async function fetchTrackAudioFeatures(trackIds: string[]): Promise<Record<string, Record<string, number>>> {
    if (!trackIds.length) return {};

    const res = await fetch(`${API_BASE}/tracks/audio-features`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track_ids: trackIds }),
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || 'Failed to fetch track audio features');
    }

    const data: TrackAudioFeaturesResponse = await res.json();
    return data.audio_features ?? {};
}
