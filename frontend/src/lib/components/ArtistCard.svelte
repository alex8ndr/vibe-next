<script lang="ts">
    import type { Track, ArtistDebugInfo } from "$lib/stores";
    import { nowPlaying, sidebarPlaying, loadingTrackId, devSettings, favoriteTracks } from "$lib/stores";
    import { trackPlayTrack, trackAddFavorite, trackRemoveFavorite } from "$lib/analytics";
    import { onMount } from "svelte";

    interface Props {
        artist: string;
        tracks: Track[];
        onAddToKnown?: () => void;
        onAddToSearch?: () => void;
        showFavoriteButton?: boolean;
        isKnown?: boolean;
        isAdded?: boolean;
        debugInfo?: ArtistDebugInfo;
    }

    let {
        artist,
        tracks,
        onAddToKnown,
        onAddToSearch,
        showFavoriteButton = false,
        isKnown = false,
        isAdded = false,
        debugInfo,
    }: Props = $props();
    
    function isFavorite(trackId: string): boolean {
        return $favoriteTracks.some(f => f.track_id === trackId);
    }
    
    function toggleFavorite(track: Track) {
        const existing = $favoriteTracks.find(f => f.track_id === track.track_id);
        if (existing) {
            favoriteTracks.update(list => list.filter(f => f.track_id !== track.track_id));
            trackRemoveFavorite(track.track_id, track.track_name, artist);
        } else {
            favoriteTracks.update(list => [...list, {
                track_id: track.track_id,
                track_name: track.track_name,
                artist_name: artist
            }]);
            trackAddFavorite(track.track_id, track.track_name, artist);
        }
    }
    
    // Format genre profile for display
    function formatGenreProfile(): string {
        if (!debugInfo?.genre_profile?.length) return '';
        return debugInfo.genre_profile
            .map(g => `${Math.round(g.pct)}% ${g.genre}`)
            .join(', ');
    }
    
    const genreProfile = $derived(formatGenreProfile());
    const showDebug = $derived($devSettings.debugMode && $devSettings.showGenreProfiles);
    const showAudioFeatures = $derived($devSettings.debugMode && $devSettings.showAudioFeatures);
    const hasTrackFeatures = $derived(tracks.some(t => t.audio_features));

    let playerEl: HTMLDivElement;
    let controller: any = null;
    let isReady = $state(false);
    let firstTrack = "";
    let currentTrackId = "";
    let showActions = $state(false);
    let isActuallyPlaying = $state(false);
    let pendingPlay: { trackId: string; trackName: string } | null = null;

    function getHue(name: string): number {
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            hash = name.charCodeAt(i) + ((hash << 5) - hash);
        }
        return Math.abs(hash) % 360;
    }

    const hue = $derived(getHue(artist));
    const isThisArtist = $derived($nowPlaying?.artist === artist);
    const playingTrackId = $derived(isThisArtist ? $nowPlaying?.trackId : null);
    const isLoadingTrack = $derived((id: string) => $loadingTrackId === id);

    onMount(() => {
        firstTrack = tracks[0]?.track_id || "";
        currentTrackId = firstTrack;

        const tryInit = () => {
            const api = (window as any).SpotifyIframeApi;
            if (!api || !playerEl || controller) return;

            api.createController(
                playerEl,
                {
                    width: "100%",
                    height: 80,
                    uri: firstTrack ? `spotify:track:${firstTrack}` : "",
                },
                (c: any) => {
                    controller = c;
                    const w = window as any;
                    w.vibeControllers = w.vibeControllers || {};
                    w.vibeControllers[artist] = c;
                    w.vibeFirstTracks = w.vibeFirstTracks || {};
                    w.vibeFirstTracks[artist] = firstTrack;

                    c.addListener("ready", () => {
                        isReady = true;
                        // Play pending track if user clicked before ready
                        if (pendingPlay) {
                            const { trackId, trackName } = pendingPlay;
                            pendingPlay = null;
                            play(trackId, trackName);
                        }
                    });
                    c.addListener("playback_update", (e: any) => {
                        const wasPlaying = isActuallyPlaying;
                        isActuallyPlaying = !e.data.isPaused;
                        
                        // Clear loading state when playback starts for this card's current track
                        if (!e.data.isPaused && $loadingTrackId === currentTrackId) {
                            loadingTrackId.set(null);
                        }
                        
                        // Sync nowPlaying when user clicks directly on embed's play/pause button
                        if (!e.data.isPaused && !wasPlaying) {
                            // Started playing - pause other cards and sidebar, set nowPlaying
                            const prev = $nowPlaying;
                            if (prev && prev.artist !== artist) {
                                window.dispatchEvent(new CustomEvent("vibeReset", { detail: prev.artist }));
                            }
                            const sidebarCtrl = (window as any).vibeSidebarController;
                            if (sidebarCtrl) {
                                try { sidebarCtrl.pause(); } catch {}
                            }
                            sidebarPlaying.set(null);
                            
                            const track = tracks.find(t => t.track_id === currentTrackId);
                            nowPlaying.set({ artist, trackId: currentTrackId, trackName: track?.track_name || "" });
                        }
                        // Don't clear nowPlaying on pause - track stays highlighted (green)
                    });
                },
            );
        };

        if ((window as any).SpotifyIframeApi) {
            tryInit();
        } else {
            const h = () => {
                tryInit();
                window.removeEventListener("SpotifyIframeApiReady", h);
            };
            window.addEventListener("SpotifyIframeApiReady", h);
        }

        const resetHandler = (e: CustomEvent) => {
            if (e.detail === artist) {
                // If we have a pending play request, cancel it to prevent race condition
                if (pendingPlay) {
                    pendingPlay = null;
                    if ($nowPlaying?.artist === artist) {
                        nowPlaying.set(null);
                    }
                }
                if (controller) {
                    controller.pause();
                    // Reload current track to avoid Spotify login nag screen (keeps same track)
                    if (currentTrackId) {
                        controller.loadUri(`spotify:track:${currentTrackId}`);
                    }
                }
                isActuallyPlaying = false;
                // Clear loading state if it was for this card
                if ($loadingTrackId === currentTrackId) {
                    loadingTrackId.set(null);
                }
            }
        };
        window.addEventListener("vibeReset", resetHandler as EventListener);
        return () =>
            window.removeEventListener(
                "vibeReset",
                resetHandler as EventListener,
            );
    });

    function play(trackId: string, trackName: string) {
        // If controller isn't ready yet, queue the play request
        if (!controller || !isReady) {
            pendingPlay = { trackId, trackName };
            loadingTrackId.set(trackId);
            nowPlaying.set({ artist, trackId, trackName });
            
            setTimeout(() => {
                if (pendingPlay && pendingPlay.trackId === trackId) {
                    pendingPlay = null;
                    loadingTrackId.set(null);
                    if ($nowPlaying?.artist === artist && $nowPlaying?.trackId === trackId) {
                        nowPlaying.set(null);
                    }
                }
            }, 8000);
            return;
        }

        const prev = $nowPlaying;

        // Track is already loaded in THIS embed - just toggle play/pause
        if (currentTrackId === trackId) {
            if (isActuallyPlaying) {
                controller.pause();
                // Don't clear nowPlaying - keep track highlighted (green) when paused
            } else {
                // Reset other cards first
                if (prev && prev.artist !== artist) {
                    window.dispatchEvent(
                        new CustomEvent("vibeReset", { detail: prev.artist }),
                    );
                }
                // Pause sidebar
                const sidebarCtrl = (window as any).vibeSidebarController;
                if (sidebarCtrl) {
                    try { sidebarCtrl.pause(); } catch {}
                }
                sidebarPlaying.set(null);
                
                // Use resume() instead of play() - this is the correct API for unpausing
                controller.resume();
                nowPlaying.set({ artist, trackId, trackName });
            }
            return;
        }

        // Different track - need to load it
        
        // Reset other artist's card if playing
        if (prev && prev.artist !== artist) {
            window.dispatchEvent(
                new CustomEvent("vibeReset", { detail: prev.artist }),
            );
        }

        // Pause sidebar player if playing
        const sidebarCtrl = (window as any).vibeSidebarController;
        if (sidebarCtrl) {
            try {
                sidebarCtrl.pause();
            } catch {}
        }
        sidebarPlaying.set(null);

        // Set loading state before starting to load
        loadingTrackId.set(trackId);
        
        // Load and play new track (small delay helps with embed race conditions)
        currentTrackId = trackId;
        controller.loadUri(`spotify:track:${trackId}`);
        setTimeout(() => controller.play(), 50);
        nowPlaying.set({ artist, trackId, trackName });
        trackPlayTrack(trackId, trackName, artist);
    }
</script>

<article
    class="card"
    class:known={isKnown}
    style:--hue={hue}
    onmouseenter={() => (showActions = true)}
    onmouseleave={() => (showActions = false)}
>
    <div class="card-header">
        <div class="title-row">
            <h3 class="title">{artist}</h3>
            {#if showDebug && genreProfile}
                <span class="genre-profile">{genreProfile}</span>
            {/if}
        </div>
        <div class="card-actions" class:visible={showActions}>
            {#if onAddToKnown}
                <button
                    class="action-btn"
                    class:active={isKnown}
                    onclick={onAddToKnown}
                    title={isKnown
                        ? "Remove from known list"
                        : "Add to known list"}
                >
                    {isKnown ? "✓" : "👁"}
                </button>
            {/if}
            {#if onAddToSearch}
                <button
                    class="action-btn"
                    onclick={onAddToSearch}
                    class:active={isAdded}
                    title={isAdded ? "Remove from search" : "Add to search"}
                >
                    {isAdded ? "-" : "+"}
                </button>
            {/if}
        </div>
    </div>

    <div class="embed-wrap">
        <div class="embed" bind:this={playerEl}></div>
        <div class="skeleton" class:hide={isReady}></div>
    </div>

    <div class="tracks">
        {#each tracks as t (t.track_id)}
            {@const isSelected = playingTrackId === t.track_id}
            {@const isLoading = isLoadingTrack(t.track_id)}
            <div class="trk-row">
                <button
                    class="trk"
                    class:playing={isSelected}
                    class:loading={isLoading}
                    onclick={() => play(t.track_id, t.track_name)}
                >
                    <span class="ico">
                        {#if isLoading}
                            <!-- Loading spinner -->
                            <svg class="spinner" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                                <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/>
                                <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
                            </svg>
                        {:else if isSelected && isActuallyPlaying}
                            <!-- Pause Icon -->
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5V19M16 5V19" stroke="currentColor" stroke-width="4" stroke-linecap="round"/></svg>
                        {:else if isSelected && !isActuallyPlaying}
                            <!-- Play Icon (paused state) -->
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                        {:else}
                            <!-- Note Icon -->
                            <svg class="note" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
                            <!-- Play Icon on hover -->
                            <svg class="play-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                        {/if}
                    </span>
                    <span class="txt">{t.track_name}</span>
                </button>
                {#if showFavoriteButton}
                    <button
                        class="fav-btn"
                        class:is-favorite={isFavorite(t.track_id)}
                        onclick={() => toggleFavorite(t)}
                        title={isFavorite(t.track_id) ? "Remove from favourites" : "Add to favourites"}
                    >
                        ♥
                    </button>
                {/if}
            </div>
            
            {#if showAudioFeatures && t.audio_features}
                <div class="audio-features">
                    <div class="audio-features-label">Song features:</div>
                    {#each Object.entries(t.audio_features) as [key, value]}
                        {#if key === 'genre'}
                            <div class="feature genre-feature">
                                <span class="feature-name">genre</span>
                                <span class="feature-value-text">{value}</span>
                            </div>
                        {:else}
                            <div class="feature">
                                <span class="feature-name">{key}</span>
                                <div class="feature-bar">
                                    <div class="feature-fill" style:width="{(value as number) * 100}%"></div>
                                </div>
                                <span class="feature-value">{(value as number).toFixed(2)}</span>
                            </div>
                        {/if}
                    {/each}
                </div>
            {:else if showAudioFeatures}
                <div class="audio-features audio-features-missing">
                    <span class="audio-features-label">No audio data - run new search with debug enabled</span>
                </div>
            {/if}
        {/each}
    </div>
</article>

<style>
    .card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 0.85rem;
        overflow: hidden;
        transition: border-color 0.15s;
    }

    .card.known {
        border-color: var(--gold);
        opacity: 0.7;
    }

    .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.6rem;
        min-height: 24px;
    }

    .title-row {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
        min-width: 0;
        flex: 1;
    }

    .title {
        font-size: 1rem;
        font-weight: 600;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    
    .genre-profile {
        font-size: 0.65rem;
        color: var(--text-3);
        font-weight: 400;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .card-actions {
        display: flex;
        gap: 0.25rem;
        opacity: 0;
        transition: opacity 0.15s;
    }

    .card-actions.visible {
        opacity: 1;
    }

    .action-btn {
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 4px;
        font-size: 0.7rem;
        color: var(--text-2);
        transition: all 0.15s;
    }

    .action-btn:hover:not(:disabled) {
        border-color: var(--gold);
        color: var(--text);
    }

    .action-btn.active {
        background: var(--gold-glow);
        border-color: var(--gold);
        color: var(--gold);
    }

    .action-btn:disabled {
        opacity: 0.5;
        cursor: default;
    }

    .embed-wrap {
        position: relative;
        height: 80px;
        border-radius: 10px;
        overflow: hidden;
        background: #121212;
        margin-bottom: 0.6rem;
    }

    .embed {
        position: absolute;
        inset: 0;
    }

    .embed :global(iframe) {
        border: none !important;
        border-radius: 10px !important;
        width: 100% !important;
        height: 80px !important;
        max-height: 80px !important;
        display: block !important;
        overflow: hidden !important;
    }

    .skeleton {
        position: absolute;
        inset: 0;
        background: linear-gradient(
            90deg,
            #181818 0%,
            #2a2a2a 40%,
            #3a3a3a 50%,
            #2a2a2a 60%,
            #181818 100%
        );
        background-size: 200% 100%;
        animation: shimmer 1.4s infinite;
        border-radius: 10px;
        transition: opacity 0.25s;
        pointer-events: none;
    }

    .skeleton.hide {
        opacity: 0;
    }

    @keyframes shimmer {
        from {
            background-position: 200% 0;
        }
        to {
            background-position: -200% 0;
        }
    }

    .tracks {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .trk-row {
        display: flex;
        gap: 0.25rem;
    }

    .trk {
        flex: 1;
        min-width: 0;
        display: flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.45rem 0.6rem;
        border: none;
        border-radius: 5px;
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 26%, 24%) 0%,
            hsl(calc(var(--hue) + 20), 20%, 18%) 100%
        );
        color: #ddd;
        font-size: 0.78rem;
        text-align: left;
        cursor: pointer;
        position: relative;
        transition: filter 0.12s;
    }

    .trk::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 2.5px;
        background: hsl(var(--hue), 50%, 48%);
        border-radius: 2px 0 0 2px;
    }

    .trk:hover {
        filter: brightness(1.1);
    }

    .trk.playing {
        background: linear-gradient(135deg, #1db954, #169c46);
        color: #fff;
    }

    .trk.loading {
        background: linear-gradient(135deg, #1db954, #169c46);
        color: #fff;
        opacity: 0.8;
    }

    .spinner {
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

    .ico {
        width: 14px;
        height: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.7;
    }

    .trk:hover .ico {
        opacity: 1;
    }

    .trk.playing .ico {
        opacity: 1;
    }

    /* Show play icon on hover if not playing */
    .trk:hover .note {
        display: none;
    }
    
    .trk .play-icon {
        display: none;
    }

    .trk:hover .play-icon {
        display: block;
    }

    .txt {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .fav-btn {
        width: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 26%, 24%) 0%,
            hsl(calc(var(--hue) + 20), 20%, 18%) 100%
        );
        border: none;
        border-radius: 5px;
        font-size: 0.7rem;
        color: #ddd;
        opacity: 0.7;
        transition: opacity 0.12s;
    }

    .fav-btn:hover {
        opacity: 1;
        color: #ff6b8a;
    }
    
    .fav-btn.is-favorite {
        opacity: 1;
        color: #ff6b8a;
    }

    @media (prefers-color-scheme: light) {
        .trk {
            background: linear-gradient(
                135deg,
                hsl(var(--hue), 20%, 38%) 0%,
                hsl(calc(var(--hue) + 20), 16%, 32%) 100%
            );
        }

        .fav-btn {
            background: linear-gradient(
                135deg,
                hsl(var(--hue), 20%, 38%) 0%,
                hsl(calc(var(--hue) + 20), 16%, 32%) 100%
            );
        }
    }

    :global([data-theme="light"]) .trk {
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 20%, 38%) 0%,
            hsl(calc(var(--hue) + 20), 16%, 32%) 100%
        );
    }

    :global([data-theme="light"]) .fav-btn {
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 20%, 38%) 0%,
            hsl(calc(var(--hue) + 20), 16%, 32%) 100%
        );
    }

    @media (hover: none) {
        .card-actions {
            opacity: 1;
        }
    }
    
    /* Audio features debug display */
    .audio-features {
        margin-top: 0.25rem;
        margin-bottom: 0.25rem;
        padding: 0.4rem 0.5rem;
        background: var(--bg-alt);
        border-radius: 5px;
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
    }
    
    .audio-features-missing {
        opacity: 0.5;
        font-style: italic;
    }
    
    .audio-features-label {
        font-size: 0.6rem;
        color: var(--text-3);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.1rem;
    }
    
    .feature {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.65rem;
    }
    
    .feature-name {
        width: 80px;
        color: var(--text-3);
        text-transform: capitalize;
    }
    
    .feature-bar {
        flex: 1;
        height: 4px;
        background: var(--bg-alt);
        border-radius: 2px;
        overflow: hidden;
    }
    
    .feature-fill {
        height: 100%;
        background: var(--gold);
        border-radius: 2px;
    }
    
    .feature-value {
        width: 35px;
        text-align: right;
        color: var(--text-2);
        font-family: monospace;
    }
    
    .genre-feature {
        display: flex;
        gap: 0.5rem;
        font-size: 0.7rem;
        padding: 0.25rem 0;
        border-top: 1px solid var(--border);
        margin-top: 0.25rem;
    }
    
    .feature-value-text {
        flex: 1;
        color: var(--text-2);
        font-style: italic;
    }
</style>
