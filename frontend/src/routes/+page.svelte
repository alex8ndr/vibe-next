<script lang="ts">
    import { onMount } from "svelte";
    import LandingView from "$lib/components/views/LandingView.svelte";
    import ResultsView from "$lib/components/views/ResultsView.svelte";
    import FeedbackForm from "$lib/components/FeedbackForm.svelte";
    import {
        fetchArtists,
        fetchRecommendationsStream,
        fetchArtistTracks,
        fetchTrackAudioFeatures,
        fetchStats,
    } from "$lib/api";
    import {
        artistsList,
        recommendations,
        recommendationsMeta,
        isLoading,
        loadingProgress,
        progressPhase,
        hasResults,
        settings,
        knownArtists,
        nowPlaying,
        sidebarPlaying,
        sidebarPlayerStatus,
        sidebarLoadingTrackId,
        devSettings,
        clientId,
        type Track,
        type FavoriteTrack,
    } from "$lib/stores";
    import "./page.css";

    let selected = $state<string[]>([]);
    let fineTune = $state<Record<string, string[]>>({}); // stores track_ids
    let artistTracks = $state<Record<string, Track[]>>({});
    let error = $state<string | null>(null);
    let regenerationHistory = $state<Set<string>>(new Set());
    let lastSearchParams = $state<string>("");
    let audioHydrationInFlight = false;
    const hydratedAudioTrackIds = new Set<string>();
    const HIDDEN_ARTIST_LIMIT = 30; // Force new search after this many total artists
    const ARTIST_PRELOAD_LIMIT = 1000;
    const MIN_PROGRESS_VISIBLE_MS = 300;
    const hitArtistLimit = $derived(regenerationHistory.size >= HIDDEN_ARTIST_LIMIT);
    let progressStartedAt = 0;

    function beginProgress() {
        progressStartedAt = performance.now();
        loadingProgress.set(0);
        progressPhase.set('active');
        isLoading.set(true);
    }

    async function finishProgress() {
        loadingProgress.set(100);
        // Ensure the bar is visible for at least MIN_PROGRESS_VISIBLE_MS
        const elapsed = performance.now() - progressStartedAt;
        const remaining = Math.max(0, MIN_PROGRESS_VISIBLE_MS - elapsed);
        if (remaining) await new Promise(r => setTimeout(r, remaining));
        // Fade out, then reset to zero while hidden
        progressPhase.set('hiding');
        await new Promise(r => setTimeout(r, 150));
        loadingProgress.set(0);
        progressPhase.set('idle');
        isLoading.set(false);
    }

    // Sidebar player
    let sidebarPlayerEl = $state<HTMLDivElement | null>(null);
    let sidebarController: any = null;
    let sidebarReady = $state(false);
    let sidebarCurrentUri = "";  // tracks what URI is loaded in the embed
    let datasetStats = $state<{ track_count: number; artist_count: number } | null>(null);

    onMount(async () => {
        (window as any).onSpotifyIframeApiReady = (IFrameAPI: any) => {
            (window as any).SpotifyIframeApi = IFrameAPI;
            window.dispatchEvent(new Event("SpotifyIframeApiReady"));
        };

        const script = document.createElement("script");
        script.src = "https://open.spotify.com/embed/iframe-api/v1";
        script.async = true;
        document.head.appendChild(script);

        try {
            const [artists, stats] = await Promise.all([
                fetchArtists("", ARTIST_PRELOAD_LIMIT),
                fetchStats().catch(() => null),
            ]);
            artistsList.set(artists);
            datasetStats = stats;
        } catch {
            error = "Could not connect to server";
        }
    });

    async function loadTracks(artist: string) {
        if (artistTracks[artist]) return;
        try {
            const t = await fetchArtistTracks(artist);
            artistTracks = { ...artistTracks, [artist]: t };
        } catch {}
    }

    $effect(() => {
        selected.forEach(loadTracks);
    });

    async function search() {
        if (!selected.length) return;
        error = null;
        beginProgress();

        const trackIds = selected.flatMap((a) => fineTune[a] || []);

        try {
            regenerationHistory = new Set();
            const res = await fetchRecommendationsStream({
                artists: selected,
                track_ids: trackIds.length ? trackIds : undefined,
                exclude_artists: $knownArtists.length
                    ? $knownArtists
                    : undefined,
                diversity: $settings.variety,
                max_artists: $settings.maxResults,
                genre_weight: $settings.genreWeight,
                tracks_per_artist: $settings.tracksPerArtist,
                vibe_mood: $settings.vibeMood,
                vibe_sound: $settings.vibeSound,
                popularity: $settings.popularity,
                debug: $devSettings.debugMode,
                debug_audio: $settings.showAudioFeatures,
                client_id: clientId,
                target_language: $settings.targetLanguage !== 'match' ? $settings.targetLanguage : undefined,
                target_genre: $settings.targetGenre !== 'match' ? $settings.targetGenre : undefined,
            }, (progress) => loadingProgress.set(progress));
            recommendations.set(res.recommendations);
            recommendationsMeta.set(res.meta ?? null);
            Object.keys(res.recommendations).forEach(artist => regenerationHistory.add(artist));
            lastSearchParams = JSON.stringify({ selected, fineTune, targetLanguage: $settings.targetLanguage, targetGenre: $settings.targetGenre });
            await finishProgress();
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
            loadingProgress.set(0);
            progressPhase.set('idle');
            isLoading.set(false);
        }
    }

    async function regenerate() {
        if (!selected.length || $isLoading) return;
        
        error = null;
        beginProgress();

        const trackIds = selected.flatMap((a) => fineTune[a] || []);

        try {
            const res = await fetchRecommendationsStream({
                artists: selected,
                track_ids: trackIds.length ? trackIds : undefined,
                exclude_artists: [...$knownArtists, ...Array.from(regenerationHistory)],
                diversity: $settings.variety,
                max_artists: $settings.maxResults,
                genre_weight: $settings.genreWeight,
                tracks_per_artist: $settings.tracksPerArtist,
                vibe_mood: $settings.vibeMood,
                vibe_sound: $settings.vibeSound,
                popularity: $settings.popularity,
                debug: $devSettings.debugMode,
                debug_audio: $settings.showAudioFeatures,
                client_id: clientId,
                target_language: $settings.targetLanguage !== 'match' ? $settings.targetLanguage : undefined,
                target_genre: $settings.targetGenre !== 'match' ? $settings.targetGenre : undefined,
            }, (progress) => loadingProgress.set(progress));
            recommendations.set(res.recommendations);
            recommendationsMeta.set(res.meta ?? null);
            const newHistory = new Set(regenerationHistory);
            Object.keys(res.recommendations).forEach(artist => newHistory.add(artist));
            regenerationHistory = newHistory;
            await finishProgress();
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
            loadingProgress.set(0);
            progressPhase.set('idle');
            isLoading.set(false);
        }
    }

    function collectMissingAudioTrackIds(currentRecommendations: Record<string, Track[]>): string[] {
        const out: string[] = [];
        for (const tracks of Object.values(currentRecommendations)) {
            for (const track of tracks) {
                if (track.audio_features) continue;
                if (hydratedAudioTrackIds.has(track.track_id)) continue;
                out.push(track.track_id);
            }
        }
        return out;
    }

    async function hydrateCurrentResultsAudioFeatures(currentRecommendations: Record<string, Track[]>) {
        if (audioHydrationInFlight) return;

        const missingTrackIds = collectMissingAudioTrackIds(currentRecommendations);
        if (!missingTrackIds.length) return;

        audioHydrationInFlight = true;
        try {
            const featuresByTrack = await fetchTrackAudioFeatures(missingTrackIds);
            const returnedTrackIds = new Set(Object.keys(featuresByTrack));

            recommendations.update((prev) => {
                const next: Record<string, Track[]> = {};
                for (const [artist, tracks] of Object.entries(prev)) {
                    next[artist] = tracks.map((track) => {
                        const features = featuresByTrack[track.track_id];
                        if (!features || track.audio_features) {
                            return track;
                        }
                        return { ...track, audio_features: features };
                    });
                }
                return next;
            });

            for (const trackId of missingTrackIds) {
                hydratedAudioTrackIds.add(trackId);
            }
            for (const trackId of returnedTrackIds) {
                hydratedAudioTrackIds.add(trackId);
            }
        } catch {
            // Keep silent to avoid noisy UX; cards will still populate after next search.
        } finally {
            audioHydrationInFlight = false;
        }
    }

    $effect(() => {
        const currentRecommendations = $recommendations;
        if (!$settings.showAudioFeatures) return;
        if ($isLoading) return;
        if (Object.keys(currentRecommendations).length === 0) return;
        void hydrateCurrentResultsAudioFeatures(currentRecommendations);
    });

    function playTrack(track: FavoriteTrack) {
        if (!sidebarReady || !sidebarController) {
            return;
        }

        const uri = `spotify:track:${track.track_id}`;

        // Same track already loaded → toggle play/pause
        if (sidebarCurrentUri === uri) {
            sidebarController.togglePlay();
            return;
        }

        // Pause any playing result card first
        const prevNowPlaying = $nowPlaying;
        if (prevNowPlaying) {
            window.dispatchEvent(
                new CustomEvent("vibeReset", { detail: prevNowPlaying.artist }),
            );
            nowPlaying.set(null);
        }

        // Set loading state and load new track
        sidebarLoadingTrackId.set(track.track_id);
        sidebarCurrentUri = uri;

        sidebarPlaying.set({
            artist: track.artist_name,
            trackId: track.track_id,
            trackName: track.track_name,
        });
    }

    // Initialize sidebar player when element is available
    $effect(() => {
        if (!sidebarPlayerEl || sidebarController) return;

        sidebarReady = false;

        const initPlayer = () => {
            const api = (window as any).SpotifyIframeApi;
            if (!api || !sidebarPlayerEl) return;

            api.createController(
                sidebarPlayerEl,
                { width: "100%", height: 80, uri: "" },
                (c: any) => {
                    sidebarController = c;
                    (window as any).vibeSidebarController = c;
                    c.addListener("ready", () => {
                        sidebarReady = true;
                        sidebarPlayerStatus.set("ready");
                    });
                    // Spotify's "ready" event may not fire for an empty URI,
                    // so treat controller creation as ready after a short delay
                    setTimeout(() => {
                        if (!sidebarReady) {
                            sidebarReady = true;
                            sidebarPlayerStatus.set("ready");
                        }
                    }, 2000);
                    c.addListener("playback_update", (e: any) => {
                        // Clear loading spinner when playback starts
                        if (!e.data.isPaused) {
                            sidebarLoadingTrackId.set(null);
                        }

                        // Detect track end → clear sidebar playing state
                        const hasEnded =
                            Boolean(e.data.isPaused) &&
                            Number(e.data.duration || 0) > 0 &&
                            Number(e.data.position || 0) >= Math.max(Number(e.data.duration || 0) - 750, 0);

                        if (hasEnded) {
                            sidebarLoadingTrackId.set(null);
                            sidebarPlaying.set(null);
                        }
                    });
                },
            );
        };

        if ((window as any).SpotifyIframeApi) {
            initPlayer();
        } else {
            const handler = () => {
                initPlayer();
                window.removeEventListener("SpotifyIframeApiReady", handler);
            };
            window.addEventListener("SpotifyIframeApiReady", handler);
        }
    });

    // Load + play when a new track is set via sidebarPlaying
    $effect(() => {
        const track = $sidebarPlaying;
        if (!track || !sidebarController || !sidebarReady) return;

        const uri = `spotify:track:${track.trackId}`;
        // Only load if this is actually a new track (not a toggle)
        if (sidebarCurrentUri !== uri) return;
        sidebarController.loadUri(uri);
        setTimeout(() => sidebarController.play(), 50);
    });
</script>

<div
    style="position: absolute; width: 0; height: 0; overflow: hidden; opacity: 0; pointer-events: none;"
>
    <!-- Global hidden player frame -->
    <div class="sidebar-player" bind:this={sidebarPlayerEl}></div>
</div>

{#if !$hasResults}
    <LandingView
        bind:selected
        bind:fineTune
        {artistTracks}
        {error}
        {datasetStats}
        onsearch={search}
        onplay={playTrack}
    />
{:else}
    <ResultsView
        bind:selected
        bind:fineTune
        {artistTracks}
        {lastSearchParams}
        {hitArtistLimit}
        {regenerationHistory}
        onsearch={search}
        onregenerate={regenerate}
        onplay={playTrack}
    />
{/if}

<FeedbackForm />
