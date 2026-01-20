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

export const nowPlaying = writable<{ artist: string; trackId: string } | null>(null);

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

export const settings = createPersistedStore('vibe-settings', {
    variety: 2,
    genreWeight: 2.0,
    maxResults: 6,
    showBackground: true
});

// Theme: 'light', 'dark', or 'system'
export const themePreference = createPersistedStore<'light' | 'dark' | 'system'>('vibe-theme', 'system');
