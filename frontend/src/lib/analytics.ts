import { API_BASE } from './apiBase';

import { clientId } from './stores';

export type EventType = 
    | 'add_favorite' 
    | 'remove_favorite' 
    | 'add_known' 
    | 'remove_known' 
    | 'play_track'
    | 'tour_started'
    | 'tour_completed'
    | 'tour_skipped'
    | 'example_clicked';

interface EventPayload {
    track_id?: string;
    track_name?: string;
    artist_name?: string;
    [key: string]: unknown;
}

export async function trackEvent(eventType: EventType, payload: EventPayload = {}): Promise<void> {
    try {
            const isMobile = typeof navigator !== 'undefined' ? /Mobile|Android|iP(ad|hone)/i.test(navigator.userAgent) : false;
            
            const enrichedPayload = {
                ...payload,
                referrer: typeof document !== 'undefined' ? document.referrer : '',
                user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
                is_mobile: isMobile,
                screen_width: typeof window !== 'undefined' ? window.innerWidth : 0,
                screen_height: typeof window !== 'undefined' ? window.innerHeight : 0,
                language: typeof navigator !== 'undefined' ? navigator.language : '',
            };

            await fetch(`${API_BASE}/log/action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    event_type: eventType,
                    client_id: clientId,
                    payload: enrichedPayload,
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

export function trackTourStarted(): void {
    trackEvent('tour_started');
}

export function trackTourCompleted(): void {
    trackEvent('tour_completed');
}

export function trackTourSkipped(step: number): void {
    trackEvent('tour_skipped', { step });
}

export function trackExampleClicked(exampleId: string): void {
    trackEvent('example_clicked', { example_id: exampleId });
}
