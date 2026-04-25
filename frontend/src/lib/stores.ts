import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';

export interface Track {
    track_id: string;
    track_name: string;
    genre?: string;
    language?: string;
    audio_features?: Record<string, number | string>;
}

export interface Recommendations {
    [artistName: string]: Track[];
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
    genre_profiles?: Record<string, Array<{ genre: string; pct: number }>>;
    debug?: Record<string, ArtistDebugInfo>;
    input_genre_profile?: Array<{ artist: string; genres: GenreInfo[] }>;
    input_language_profile?: Array<{ artist: string; languages: Array<{ language: string; pct: number }> }>;
    search_vector_audio?: Record<string, number>;
    search_vector_genre?: GenreInfo[];
}

export const recommendations = writable<Recommendations>({});
export const recommendationsMeta = writable<RecommendMeta | null>(null);
export const artistsList = writable<string[]>([]);
export const isLoading = writable(false);
export const loadingProgress = writable<number>(0);
export const progressPhase = writable<'idle' | 'active' | 'hiding'>('idle');
export const hasResults = derived(recommendations, ($r) => Object.keys($r).length > 0);

export const nowPlaying = writable<{ artist: string; trackId: string; trackName: string } | null>(null);

// Separate store for sidebar player (favorites only, doesn't interfere with result cards)
export const sidebarPlaying = writable<{ artist: string; trackId: string; trackName: string } | null>(null);

export type SidebarPlayerStatus = 'loading' | 'ready' | 'unavailable';
export const sidebarPlayerStatus = writable<SidebarPlayerStatus>('loading');

// Loading state for result card tracks (shows loading indicator while track loads)
export const loadingTrackId = writable<string | null>(null);

// Loading state for sidebar tracks
export const sidebarLoadingTrackId = writable<string | null>(null);

// Mobile sidebar visibility
export const mobileSidebarOpen = writable(false);

// Sidebar player compact mode (hides embed, shows only track info)
export const playerCompact = createPersistedStore<boolean>('vibe-player-compact', true);

// Settings with localStorage persistence
function createPersistedStore<T>(key: string, initial: T) {
    let stored: string | null = null;
    if (browser) {
        try {
            stored = localStorage.getItem(key);
        } catch {
            // Safari private mode or quota errors
        }
    }
    let value: T = initial;
    if (stored) {
        try {
            value = JSON.parse(stored);
        } catch {
            value = initial;
        }
    }
    const store = writable<T>(value);

    if (browser) {
        store.subscribe((v) => {
            try {
                localStorage.setItem(key, JSON.stringify(v));
            } catch {
                // Safari private mode or quota errors
            }
        });
    }

    return store;
}

// Configurable limits
export const LIMITS = {
    MAX_INPUT_ARTISTS: 5,
    MAX_INPUT_SONGS_PER_ARTIST: 5,
    MAX_RESULT_ARTISTS: { min: 3, max: 12, default: 9 },
    MAX_TRACKS_PER_ARTIST: { min: 2, max: 6, default: 3 }
} as const;

export const DEFAULT_SETTINGS = {
    variety: 0,
    genreWeight: 2,
    maxResults: LIMITS.MAX_RESULT_ARTISTS.default,
    tracksPerArtist: LIMITS.MAX_TRACKS_PER_ARTIST.default,
    showBackground: true,
    showGenres: true,
    showLanguages: false,
    showAudioFeatures: false,
    // Vibe modifiers: -1 to +1 sliders
    vibeMood: 0,   // Chill (-1) to Energetic (+1)
    vibeSound: 0,  // Acoustic (-1) to Electronic (+1)
    popularity: 0, // Hidden Gems (-1) to Mainstream (+1)
    // Advanced targeting 
    targetLanguage: 'match' as string,
    targetGenre: 'match' as string,
};

export const settings = createPersistedStore('vibe-settings', DEFAULT_SETTINGS);

if (browser) {
    settings.update((current) => ({
        ...DEFAULT_SETTINGS,
        ...current,
        showGenres: current.showGenres ?? true,
        showLanguages: current.showLanguages ?? false,
        showAudioFeatures: current.showAudioFeatures ?? false,
    }));
}

// Theme: 'light', 'dark', or 'system'
export const themePreference = createPersistedStore<'light' | 'dark' | 'system'>('vibe-theme', 'system');

// User lists (persistent)
export interface FavoriteTrack {
    track_id: string;
    track_name: string;
    artist_name: string;
}

export const knownArtists = createPersistedStore<string[]>('vibe-known-artists', []);
export const favoriteTracks = createPersistedStore<FavoriteTrack[]>('vibe-favorites', []);

// UI state for right panel
export const rightPanelOpen = createPersistedStore<boolean>('vibe-right-panel', true);

// Dev settings (only visible in dev mode)
export const devSettings = createPersistedStore('vibe-dev-settings', {
    debugMode: false,
});

// Client ID for analytics (persisted per-browser)
function generateClientId(): string {
    // randomUUID is unavailable on some HTTP/non-secure contexts.
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }

    if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
        const bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }

    const rand = Math.random().toString(36).slice(2);
    return `vibe-${Date.now()}-${rand}`;
}

function getOrCreateClientId(): string {
    if (!browser) return 'ssr';
    const key = 'vibe-client-id';
    let id: string | null = null;
    try {
        id = localStorage.getItem(key);
    } catch {
        // Safari private mode or quota errors
    }
    if (!id) {
        id = generateClientId();
        try {
            localStorage.setItem(key, id);
        } catch {
            // Safari private mode or quota errors
        }
    }
    return id;
}

export const clientId = browser ? getOrCreateClientId() : 'ssr';
