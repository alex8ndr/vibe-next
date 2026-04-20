<script lang="ts">
    import type { Track } from "$lib/stores";
    import { nowPlaying, sidebarPlaying, loadingTrackId, favoriteTracks, settings } from "$lib/stores";
    import { trackPlayTrack, trackAddFavorite, trackRemoveFavorite } from "$lib/analytics";
    import { onMount } from "svelte";

    interface DisplayFeature {
        key: string;
        label: string;
        value: number;
        barValue: number;
    }

    const AUDIO_FEATURE_KEYS = [
        "energy",
        "danceability",
        "acousticness",
        "valence",
        "tempo",
        "instrumentalness",
    ] as const;

    const AUDIO_FEATURE_LABELS: Record<string, string> = {
        energy: "Energy",
        danceability: "Dance",
        acousticness: "Acoustic",
        valence: "Mood",
        tempo: "Tempo",
        instrumentalness: "Instrumental",
    };

    const LANGUAGE_NAMES: Record<string, string> = {
        en: "English",
        es: "Spanish",
        pt: "Portuguese",
        ja: "Japanese",
        de: "German",
        fr: "French",
        zh: "Chinese",
        it: "Italian",
        ru: "Russian",
        tr: "Turkish",
        fi: "Finnish",
        ko: "Korean",
        id: "Indonesian",
        hi: "Hindi",
        pl: "Polish",
        sv: "Swedish",
        ar: "Arabic",
        th: "Thai",
        nl: "Dutch",
        no: "Norwegian",
        da: "Danish",
        tl: "Tagalog",
        cs: "Czech",
        hu: "Hungarian",
        ta: "Tamil",
        pa: "Punjabi",
        ms: "Malay",
        vi: "Vietnamese",
        el: "Greek",
        he: "Hebrew",
        ml: "Malayalam",
        ro: "Romanian",
        fa: "Persian",
        uk: "Ukrainian",
        te: "Telugu",
        is: "Icelandic",
        bg: "Bulgarian",
        lt: "Lithuanian",
        lv: "Latvian",
        hr: "Croatian",
        et: "Estonian",
        am: "Amharic",
        sk: "Slovak",
        sq: "Albanian",
        sl: "Slovenian",
        ur: "Urdu",
        sr: "Serbian",
        ca: "Catalan",
        af: "Afrikaans",
        hy: "Armenian",
        ne: "Nepali",
        eo: "Esperanto",
    };

    interface Props {
        artist: string;
        tracks: Track[];
        onAddToKnown?: () => void;
        onAddToSearch?: () => void;
        showFavoriteButton?: boolean;
        isKnown?: boolean;
        isAdded?: boolean;
        genreProfile?: Array<{ genre: string; pct: number }>;
        staggerIndex?: number;
    }

    let {
        artist,
        tracks,
        onAddToKnown,
        onAddToSearch,
        showFavoriteButton = false,
        isKnown = false,
        isAdded = false,
        genreProfile,
        staggerIndex = 0,
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
        if (!genreProfile?.length) return '';
        return genreProfile
            .map(g => g.genre)
            .join(', ');
    }

    function formatLanguageCode(language: string): string {
        const normalized = language.trim().toLowerCase();
        if (!normalized) return '';
        if (LANGUAGE_NAMES[normalized]) return LANGUAGE_NAMES[normalized];
        if (normalized.length === 2) return normalized.toUpperCase();
        return language.trim().replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function formatLanguageProfile(): string {
        const counts = new Map<string, number>();
        for (const t of tracks) {
            const raw = typeof t.language === 'string' ? t.language : '';
            const label = formatLanguageCode(raw);
            if (!label) continue;
            counts.set(label, (counts.get(label) ?? 0) + 1);
        }
        if (counts.size === 0) return '';
        return [...counts.entries()]
            .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
            .map(([label]) => label)
            .join(', ');
    }

    function clamp01(value: number): number {
        return Math.max(0, Math.min(1, value));
    }

    function normalizeFeatureValue(key: string, value: number): number {
        if (key === 'tempo') {
            if (value > 1.5) return clamp01(value / 200);
            return clamp01(value);
        }
        if (value > 1.0) return clamp01(value / 100);
        return clamp01(value);
    }

    function getTrackAudioFeatures(track: Track): DisplayFeature[] {
        const features = track.audio_features;
        if (!features) return [];

        return AUDIO_FEATURE_KEYS.flatMap((key): DisplayFeature[] => {
            const raw = features[key];
            if (typeof raw !== 'number' || !Number.isFinite(raw)) {
                return [];
            }
            return [{
                key,
                label: AUDIO_FEATURE_LABELS[key] ?? key,
                value: raw,
                barValue: normalizeFeatureValue(key, raw),
            }];
        });
    }
    
    const genreProfileText = $derived(formatGenreProfile());
    const languageProfile = $derived(formatLanguageProfile());
    const showGenres = $derived($settings.showGenres);
    const showLanguages = $derived($settings.showLanguages);
    const showAudioFeatures = $derived($settings.showAudioFeatures);

    // Stagger config: delay between each card's iframe init (ms)
    const STAGGER_DELAY_MS = 150;

    let playerEl: HTMLDivElement;
    let controller: any = null;
    let isReady = $state(false);
    let embedStatus = $state<"loading" | "ready" | "unavailable">("loading");
    let firstTrack = "";
    let currentTrackId = "";
    let showActions = $state(false);
    let isActuallyPlaying = $state(false);
    let playerMessage = $state<string | null>(null);
    let loadingTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let initTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let staggerTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let playGeneration = 0;

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
    const canUseEmbed = $derived(embedStatus === "ready");

    function clearLoadingTimeout() {
        if (loadingTimeoutId) {
            clearTimeout(loadingTimeoutId);
            loadingTimeoutId = null;
        }
    }

    function startLoadingTimeout(trackId: string) {
        clearLoadingTimeout();
        loadingTimeoutId = setTimeout(() => {
            if ($loadingTrackId === trackId) {
                loadingTrackId.set(null);
            }
            if ($nowPlaying?.artist === artist && $nowPlaying?.trackId === trackId && !isActuallyPlaying) {
                nowPlaying.set(null);
            }
            playerMessage = "Spotify preview timed out. Try again or use the embed controls.";
        }, 10000);
    }

    function stopSidebarPlayback() {
        const sidebarCtrl = (window as any).vibeSidebarController;
        if (sidebarCtrl) {
            try {
                sidebarCtrl.pause();
            } catch {}
        }
        sidebarPlaying.set(null);
    }

    onMount(() => {
        firstTrack = tracks[0]?.track_id || "";
        currentTrackId = firstTrack;
        embedStatus = "loading";
        playerMessage = null;

        const tryInit = () => {
            const api = (window as any).SpotifyIframeApi;
            if (!api || !playerEl || controller) return;

            if (initTimeoutId) {
                clearTimeout(initTimeoutId);
            }
            initTimeoutId = setTimeout(() => {
                if (!isReady) {
                    embedStatus = "unavailable";
                    playerMessage = "Spotify preview did not initialize for this card.";
                    if ($loadingTrackId === currentTrackId) {
                        loadingTrackId.set(null);
                    }
                }
            }, 15000);

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
                        embedStatus = "ready";
                        playerMessage = null;
                        if (initTimeoutId) {
                            clearTimeout(initTimeoutId);
                            initTimeoutId = null;
                        }
                    });
                    c.addListener("playback_update", (e: any) => {
                        const wasPlaying = isActuallyPlaying;
                        const hasEnded =
                            Boolean(e.data.isPaused) &&
                            Number(e.data.duration || 0) > 0 &&
                            Number(e.data.position || 0) >= Math.max(Number(e.data.duration || 0) - 750, 0);

                        isActuallyPlaying = !e.data.isPaused;

                        // Clear loading state when playback starts for this card's current track
                        if (!e.data.isPaused && $loadingTrackId === currentTrackId) {
                            loadingTrackId.set(null);
                            clearLoadingTimeout();
                            playerMessage = null;
                        }
                        
                        // Sync nowPlaying when user clicks directly on embed's play/pause button
                        if (!e.data.isPaused && !wasPlaying) {
                            // Started playing - pause other cards and sidebar, set nowPlaying
                            const prev = $nowPlaying;
                            if (prev && prev.artist !== artist) {
                                window.dispatchEvent(new CustomEvent("vibeReset", { detail: prev.artist }));
                            }
                            stopSidebarPlayback();
                            
                            const track = tracks.find(t => t.track_id === currentTrackId);
                            nowPlaying.set({ artist, trackId: currentTrackId, trackName: track?.track_name || "" });
                        }

                        if (hasEnded) {
                            isActuallyPlaying = false;
                            loadingTrackId.set(null);
                            clearLoadingTimeout();
                            if ($nowPlaying?.artist === artist && $nowPlaying?.trackId === currentTrackId) {
                                nowPlaying.set(null);
                            }
                        }
                    });
                },
            );
        };

        const staggeredInit = () => {
            const delay = staggerIndex * STAGGER_DELAY_MS;
            if (delay > 0) {
                staggerTimeoutId = setTimeout(tryInit, delay);
            } else {
                tryInit();
            }
        };

        if ((window as any).SpotifyIframeApi) {
            staggeredInit();
        } else {
            const h = () => {
                staggeredInit();
                window.removeEventListener("SpotifyIframeApiReady", h);
            };
            window.addEventListener("SpotifyIframeApiReady", h);
        }

        const resetHandler = (e: CustomEvent) => {
            if (e.detail === artist) {
                playGeneration++;
                if (controller) {
                    controller.pause();
                    if (currentTrackId) {
                        controller.loadUri(`spotify:track:${currentTrackId}`);
                    }
                }
                isActuallyPlaying = false;
                if ($loadingTrackId === currentTrackId) {
                    loadingTrackId.set(null);
                }
                clearLoadingTimeout();
            }
        };
        window.addEventListener("vibeReset", resetHandler as EventListener);
        return () => {
            clearLoadingTimeout();
            if (initTimeoutId) {
                clearTimeout(initTimeoutId);
            }
            if (staggerTimeoutId) {
                clearTimeout(staggerTimeoutId);
            }
            window.removeEventListener(
                "vibeReset",
                resetHandler as EventListener,
            );
        };
    });

    function play(trackId: string, trackName: string) {
        if (!controller || !isReady || embedStatus !== "ready") {
            return;
        }

        // If another track is loading, cancel it and proceed with the new one
        if ($loadingTrackId && $loadingTrackId !== trackId) {
            loadingTrackId.set(null);
        }
        clearLoadingTimeout();
        playerMessage = null;

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
                stopSidebarPlayback();
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

        stopSidebarPlayback();

        // Set loading state before starting to load
        loadingTrackId.set(trackId);
        startLoadingTimeout(trackId);
        
        // Load new track
        currentTrackId = trackId;
        const gen = ++playGeneration;
        controller.loadUri(`spotify:track:${trackId}`);
        setTimeout(() => {
            if (playGeneration === gen) controller.play();
        }, 50);
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
            {#if showLanguages && languageProfile}
                <span class="genre-sep">·</span>
                <span class="genre-profile">{languageProfile}</span>
            {/if}
            {#if showGenres && genreProfileText}
                <span class="genre-sep">·</span>
                <span class="genre-profile">{genreProfileText}</span>
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
    {#if playerMessage}
        <p class="embed-message">{playerMessage}</p>
    {/if}

    <div class="tracks">
        {#each tracks as t (t.track_id)}
            {@const isSelected = playingTrackId === t.track_id}
            {@const isLoading = isLoadingTrack(t.track_id)}
            {@const audioFeatures = showAudioFeatures ? getTrackAudioFeatures(t) : []}
            <div class="trk-row">
                <button
                    class="trk"
                    class:playing={isSelected}
                    class:loading={isLoading}
                    disabled={!canUseEmbed}
                    title={canUseEmbed ? "Play preview" : embedStatus === "loading" ? "Spotify preview is still loading" : "Spotify preview is unavailable"}
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
                {#if showAudioFeatures && audioFeatures.length > 0}
                    <div
                        class="audio-hover-zone"
                        tabindex="0"
                        role="button"
                        aria-label={`Show audio features for ${t.track_name}`}
                    >
                        <svg class="audio-hover-glyph" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="5" y1="20" x2="5" y2="12" />
                            <line x1="12" y1="20" x2="12" y2="8" />
                            <line x1="19" y1="20" x2="19" y2="4" />
                        </svg>
                        <div class="audio-hover-popover" role="tooltip">
                            <div class="audio-features-label">Song Features</div>
                            {#each audioFeatures as feature (feature.key)}
                                <div class="feature">
                                    <span class="feature-name">{feature.label}</span>
                                    <div class="feature-bar">
                                        <div class="feature-fill" style:width={`${feature.barValue * 100}%`}></div>
                                    </div>
                                    <span class="feature-value">{feature.value.toFixed(2)}</span>
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}
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
        align-items: center;
        gap: 0.4rem;
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
        min-width: 0;
    }
    
    .genre-sep {
        color: var(--text-3);
        font-size: 0.85rem;
        flex-shrink: 0;
    }

    .genre-profile {
        font-size: 0.75rem;
        color: var(--text-3);
        font-weight: 400;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex-shrink: 1;
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

    .embed-message {
        margin: -0.15rem 0 0.5rem 0;
        font-size: 0.68rem;
        color: var(--text-3);
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
        align-items: stretch;
        gap: 0.25rem;
    }

    .trk {
        --trk-sat: 26%;
        --trk-lit: 24%;
        --trk-sat2: 20%;
        --trk-lit2: 18%;
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
            hsl(var(--hue), var(--trk-sat), var(--trk-lit)) 0%,
            hsl(calc(var(--hue) + 20), var(--trk-sat2), var(--trk-lit2)) 100%
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

    .trk:disabled {
        cursor: not-allowed;
        opacity: 0.55;
        filter: none;
    }

    .trk:disabled:hover {
        filter: none;
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

    .audio-hover-zone {
        position: relative;
        width: 24px;
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
        color: #ddd;
        opacity: 0.7;
        cursor: pointer;
        outline: none;
    }

    .audio-hover-zone:focus-visible {
        box-shadow: 0 0 0 1px var(--gold);
        opacity: 1;
    }

    .audio-hover-glyph {
        opacity: 0.9;
    }

    .audio-hover-popover {
        position: absolute;
        bottom: calc(100% + 0.2rem);
        right: 0;
        width: 220px;
        padding: 0.45rem 0.5rem;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 6px;
        box-shadow: 0 4px 10px var(--shadow);
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        opacity: 0;
        transform: translateY(2px);
        pointer-events: none;
        transition: opacity 0.12s ease, transform 0.12s ease;
        z-index: 5;
    }

    .audio-hover-zone:hover,
    .audio-hover-zone:active,
    .audio-hover-zone:focus-within {
        opacity: 1;
    }

    .audio-hover-zone:hover .audio-hover-popover,
    .audio-hover-zone:active .audio-hover-popover,
    .audio-hover-zone:focus-within .audio-hover-popover {
        opacity: 1;
        transform: translateY(0);
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
            --trk-sat: 20%;
            --trk-lit: 38%;
            --trk-sat2: 16%;
            --trk-lit2: 32%;
        }

        .audio-hover-zone,
        .fav-btn {
            background: linear-gradient(
                135deg,
                hsl(var(--hue), 20%, 38%) 0%,
                hsl(calc(var(--hue) + 20), 16%, 32%) 100%
            );
        }
    }

    :global([data-theme="light"]) .trk {
        --trk-sat: 20%;
        --trk-lit: 38%;
        --trk-sat2: 16%;
        --trk-lit2: 32%;
    }

    :global([data-theme="light"]) .audio-hover-zone,
    :global([data-theme="light"]) .fav-btn {
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 20%, 38%) 0%,
            hsl(calc(var(--hue) + 20), 16%, 32%) 100%
        );
    }

    /* Playing/loading states MUST come after theme blocks to win specificity */
    .trk.playing {
        --trk-sat: 60%;
        --trk-lit: 30%;
        --trk-sat2: 30%;
        --trk-lit2: 24%;
        color: #fff;
    }

    .trk.playing::before {
        background: hsl(var(--hue), 60%, 58%);
        width: 3px;
    }

    .trk.loading {
        --trk-sat: 35%;
        --trk-lit: 28%;
        --trk-sat2: 30%;
        --trk-lit2: 22%;
        color: #fff;
        animation: pulse-loading 1.5s ease-in-out infinite;
    }

    @keyframes pulse-loading {
        0%, 100% { opacity: 0.7; }
        50% { opacity: 1; }
    }

    @media (hover: none) {
        .card-actions {
            opacity: 1;
        }
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
        width: 38px;
        text-align: right;
        color: var(--text-2);
        font-family: monospace;
    }
</style>
