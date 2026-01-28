<script lang="ts">
    import { onMount } from "svelte";
    import LandingView from "$lib/components/views/LandingView.svelte";
    import ResultsView from "$lib/components/views/ResultsView.svelte";
    import {
        fetchArtists,
        fetchRecommendations,
        fetchArtistTracks,
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
        devSettings,
        clientId,
        type Track,
        type FavoriteTrack,
    } from "$lib/stores";
    import "./page.css";

    let selected = $state<string[]>([]);
    let fineTune = $state<Record<string, string[]>>({});
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
    let sidebarActuallyPlaying = $state(false);

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
            const artists = await fetchArtists("", 5000);
            artistsList.set(artists);
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

        const trackIds: string[] = [];
        for (const a of selected) {
            (fineTune[a] || []).forEach((name) => {
                const t = (artistTracks[a] || []).find(
                    (x) => x.track_name === name,
                );
                if (t) trackIds.push(t.track_id);
            });
        }

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

        const trackIds: string[] = [];
        for (const a of selected) {
            (fineTune[a] || []).forEach((name) => {
                const t = (artistTracks[a] || []).find((x) => x.track_name === name);
                if (t) trackIds.push(t.track_id);
            });
        }

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
            Object.keys(res.recommendations).forEach(artist => regenerationHistory.add(artist));
            clearInterval(progressInterval);
            isLoading.set(false);
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
            clearInterval(progressInterval);
            isLoading.set(false);
        }
    }

    function playTrack(track: FavoriteTrack) {
        // Toggle if clicking the same track
        if ($sidebarPlaying?.trackId === track.track_id && sidebarController) {
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

        // Update sidebar playing state
        sidebarPlaying.set({
            artist: track.artist_name,
            trackId: track.track_id,
            trackName: track.track_name,
        });
    }

    // Initialize sidebar player when element is available
    $effect(() => {
        if (!sidebarPlayerEl || sidebarController) return;

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
                    });
                    c.addListener("playback_update", (e: any) => {
                        sidebarActuallyPlaying = !e.data.isPaused;
                    });
                    setTimeout(() => {
                        sidebarReady = true;
                    }, 2000);
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

    // Update sidebar player when track changes
    $effect(() => {
        const track = $sidebarPlaying;
        if (!track || !sidebarController) return;

        sidebarController.loadUri(`spotify:track:${track.trackId}`);
        sidebarController.play();
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
        onsearch={search}
        onregenerate={regenerate}
        onplay={playTrack}
    />
{/if}
