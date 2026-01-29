const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

import { clientId } from './stores';

export type EventType = 
    | 'add_favorite' 
    | 'remove_favorite' 
    | 'add_known' 
    | 'remove_known' 
    | 'play_track';

interface EventPayload {
    track_id?: string;
    track_name?: string;
    artist_name?: string;
    [key: string]: unknown;
}

export async function trackEvent(eventType: EventType, payload: EventPayload = {}): Promise<void> {
    try {
        await fetch(`${API_BASE}/log/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_type: eventType,
                client_id: clientId,
                payload: payload,
            }),
        });
    } catch {
        // Silent fail - analytics should never break the app
    }
}

export function trackAddFavorite(trackId: string, trackName: string, artistName: string): void {
    trackEvent('add_favorite', { track_id: trackId, track_name: trackName, artist_name: artistName });
}

export function trackRemoveFavorite(trackId: string, trackName: string, artistName: string): void {
    trackEvent('remove_favorite', { track_id: trackId, track_name: trackName, artist_name: artistName });
}

export function trackAddKnown(artistName: string): void {
    trackEvent('add_known', { artist_name: artistName });
}

export function trackRemoveKnown(artistName: string): void {
    trackEvent('remove_known', { artist_name: artistName });
}

export function trackPlayTrack(trackId: string, trackName: string, artistName: string): void {
    trackEvent('play_track', { track_id: trackId, track_name: trackName, artist_name: artistName });
}
