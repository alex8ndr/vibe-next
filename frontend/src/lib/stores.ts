import { writable, derived } from 'svelte/store';

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

// Global playback state - only ONE track can be "playing" at a time
export const nowPlaying = writable<{ artist: string; trackId: string } | null>(null);
