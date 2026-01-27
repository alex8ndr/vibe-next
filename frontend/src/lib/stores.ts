import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';

export interface Track {
    track_id: string;
    track_name: string;
}

export interface Recommendations {
    [artistName: string]: Track[];
}

export const recommendations = writable<Recommendations>({});
export const artistsList = writable<string[]>([]);
export const isLoading = writable(false);
export const hasResults = derived(recommendations, ($r) => Object.keys($r).length > 0);

export const nowPlaying = writable<{ artist: string; trackId: string; trackName: string } | null>(null);

// Separate store for sidebar player (favorites only, doesn't interfere with result cards)
export const sidebarPlaying = writable<{ artist: string; trackId: string; trackName: string } | null>(null);

// Mobile sidebar visibility
export const mobileSidebarOpen = writable(false);

// Sidebar player compact mode (hides embed, shows only track info)
export const playerCompact = createPersistedStore<boolean>('vibe-player-compact', true);

// Settings with localStorage persistence
function createPersistedStore<T>(key: string, initial: T) {
    const stored = browser ? localStorage.getItem(key) : null;
    const value = stored ? JSON.parse(stored) : initial;
    const store = writable<T>(value);

    if (browser) {
        store.subscribe((v) => localStorage.setItem(key, JSON.stringify(v)));
    }

    return store;
}

// Configurable limits
export const LIMITS = {
    MAX_INPUT_ARTISTS: 5,
    MAX_INPUT_SONGS_PER_ARTIST: 5,
    MAX_RESULT_ARTISTS: { min: 3, max: 12, default: 6 },
    MAX_TRACKS_PER_ARTIST: { min: 2, max: 6, default: 4 }
} as const;

export const settings = createPersistedStore('vibe-settings', {
    variety: 2,
    genreWeight: 2.0,
    maxResults: LIMITS.MAX_RESULT_ARTISTS.default,
    tracksPerArtist: LIMITS.MAX_TRACKS_PER_ARTIST.default,
    showBackground: true,
    // Vibe modifiers: -1 to +1 sliders
    vibeMood: 0,   // Chill (-1) to Energetic (+1)
    vibeSound: 0,  // Acoustic (-1) to Electronic (+1)
    popularity: 0, // Hidden Gems (-1) to Mainstream (+1)
});

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
