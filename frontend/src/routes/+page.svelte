<script lang="ts">
    import { onMount } from "svelte";
    import LandingView from "$lib/components/views/LandingView.svelte";
    import ResultsView from "$lib/components/views/ResultsView.svelte";
    import FeedbackForm from "$lib/components/FeedbackForm.svelte";
    import {
        fetchArtists,
        fetchRecommendations,
        fetchArtistTracks,
        fetchStats,
    } from "$lib/api";
    import {
        artistsList,
        recommendations,
        recommendationsMeta,
        isLoading,
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
    let loadingProgress = $state(0);
    let regenerationHistory = $state<Set<string>>(new Set());
    let lastSearchParams = $state<string>("");
    const HIDDEN_ARTIST_LIMIT = 30; // Force new search after this many total artists
    const hitArtistLimit = $derived(regenerationHistory.size >= HIDDEN_ARTIST_LIMIT);

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
                fetchArtists("", 5000),
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
        isLoading.set(true);
        loadingProgress = 0;

        const progressInterval = setInterval(() => {
            loadingProgress = Math.min(
                loadingProgress + Math.random() * 15,
                90,
            );
        }, 150);

        // fineTune now stores track_ids directly, no lookup needed
        const trackIds = selected.flatMap((a) => fineTune[a] || []);

        try {
            // Reset regeneration history on new search
            regenerationHistory = new Set();
            const res = await fetchRecommendations({
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
                debug_audio: $devSettings.debugMode && $devSettings.showAudioFeatures,
                client_id: clientId,
            });
            loadingProgress = 100;
            recommendations.set(res.recommendations);
            recommendationsMeta.set(res.meta ?? null);
            // Add newly recommended artists to history so regenerate() excludes them
            Object.keys(res.recommendations).forEach(artist => regenerationHistory.add(artist));
            // Store params to detect when they've changed
            lastSearchParams = JSON.stringify({ selected, fineTune });
            clearInterval(progressInterval);
            isLoading.set(false);
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
            clearInterval(progressInterval);
            isLoading.set(false);
        }
    }

    async function regenerate() {
        if (!selected.length || $isLoading) return;
        
        error = null;
        isLoading.set(true);
        loadingProgress = 0;

        const progressInterval = setInterval(() => {
            loadingProgress = Math.min(loadingProgress + Math.random() * 15, 90);
        }, 150);

        // fineTune now stores track_ids directly, no lookup needed
        const trackIds = selected.flatMap((a) => fineTune[a] || []);

        try {
            const res = await fetchRecommendations({
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
                debug_audio: $devSettings.debugMode && $devSettings.showAudioFeatures,
                client_id: clientId,
            });
            loadingProgress = 100;
            recommendations.set(res.recommendations);
            recommendationsMeta.set(res.meta ?? null);
            // Add newly recommended artists to history
            const newHistory = new Set(regenerationHistory);
            Object.keys(res.recommendations).forEach(artist => newHistory.add(artist));
            regenerationHistory = newHistory;
            clearInterval(progressInterval);
            isLoading.set(false);
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
            clearInterval(progressInterval);
            isLoading.set(false);
        }
    }

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
        {loadingProgress}
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
