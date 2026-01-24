<script lang="ts">
    import { onMount } from "svelte";
    import ArtistSelect from "$lib/components/ArtistSelect.svelte";
    import ArtistCard from "$lib/components/ArtistCard.svelte";
    import {
        fetchArtists,
        fetchRecommendations,
        fetchArtistTracks,
    } from "$lib/api";
    import bgDark from "$lib/assets/background_dark.webp";
    import bgLight from "$lib/assets/background_light.webp";
    import {
        artistsList,
        recommendations,
        isLoading,
        hasResults,
        settings,
        knownArtists,
        favoriteTracks,
        rightPanelOpen,
        nowPlaying,
        sidebarPlaying,
        mobileSidebarOpen,
        LIMITS,
        type Track,
        type FavoriteTrack,
    } from "$lib/stores";

    let selected = $state<string[]>([]);
    let fineTune = $state<Record<string, string[]>>({});
    let artistTracks = $state<Record<string, Track[]>>({});
    let expandedArtists = $state<Set<string>>(new Set());
    let heroExpandedArtist = $state<string | null>(null);
    let error = $state<string | null>(null);
    let globalSongSearch = $state("");
    let loadingProgress = $state(0);

    // Sidebar player
    let sidebarPlayerEl = $state<HTMLDivElement | null>(null);
    let sidebarController: any = null;
    let sidebarReady = $state(false);

    const atMaxArtists = $derived(selected.length >= LIMITS.MAX_INPUT_ARTISTS);

    // Group favorites by artist for display
    const favoritesByArtist = $derived.by(() => {
        const map: Record<string, typeof $favoriteTracks> = {};
        for (const fav of $favoriteTracks) {
            if (!map[fav.artist_name]) map[fav.artist_name] = [];
            map[fav.artist_name].push(fav);
        }
        return map;
    });

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
            });
            loadingProgress = 100;
            recommendations.set(res.recommendations);
            clearInterval(progressInterval);
            isLoading.set(false);
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
            clearInterval(progressInterval);
            isLoading.set(false);
        }
    }

    function toggleSong(artist: string, song: string) {
        const cur = fineTune[artist] || [];
        if (cur.includes(song)) {
            fineTune = { ...fineTune, [artist]: cur.filter((s) => s !== song) };
        } else if (cur.length < LIMITS.MAX_INPUT_SONGS_PER_ARTIST) {
            fineTune = { ...fineTune, [artist]: [...cur, song] };
        }
    }

    function isAtSongLimit(artist: string): boolean {
        return (
            (fineTune[artist]?.length || 0) >= LIMITS.MAX_INPUT_SONGS_PER_ARTIST
        );
    }

    function toggleExpanded(artist: string) {
        const next = new Set(expandedArtists);
        if (next.has(artist)) {
            next.delete(artist);
        } else {
            next.add(artist);
        }
        expandedArtists = next;
    }

    function toggleHeroExpanded(artist: string) {
        heroExpandedArtist = heroExpandedArtist === artist ? null : artist;
    }

    function getFilteredTracks(
        artist: string,
        searchQuery: string = "",
    ): Track[] {
        const tracks = artistTracks[artist] || [];
        const query = searchQuery.toLowerCase();
        if (!query) return tracks;
        return tracks.filter((t) => t.track_name.toLowerCase().includes(query));
    }

    function addToKnown(artist: string) {
        knownArtists.update((list) => {
            if (list.includes(artist)) return list;
            return [...list, artist];
        });
    }

    function removeFromKnown(artist: string) {
        knownArtists.update((list) => list.filter((a) => a !== artist));
    }

    function addToSearch(artist: string) {
        if (
            !selected.includes(artist) &&
            selected.length < LIMITS.MAX_INPUT_ARTISTS
        ) {
            selected = [...selected, artist];
        }
    }

    function addFavorite(track: Track, artist: string) {
        favoriteTracks.update((list) => {
            if (list.some((t) => t.track_id === track.track_id)) return list;
            return [...list, { ...track, artist_name: artist }];
        });
    }

    function removeFavorite(trackId: string) {
        favoriteTracks.update((list) =>
            list.filter((t) => t.track_id !== trackId),
        );
    }

    function playTrack(track: FavoriteTrack) {
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

    function generateHTML(): string {
        const inputArtists = selected.join(" • ");

        let cards = "";
        for (const [artist, tracks] of Object.entries($recommendations)) {
            const artistId = artist.replace(/[^a-zA-Z0-9]/g, "_");
            const firstTrack = tracks[0]?.track_id || "";

            let trackButtons = "";
            for (let i = 0; i < tracks.length; i++) {
                const track = tracks[i];
                const active = i === 0 ? "active" : "";
                const safeName = track.track_name.replace(/"/g, "&quot;");
                trackButtons += `<button class="track-btn ${active}" onclick="playTrack(this, '${track.track_id}')">${safeName}</button>`;
            }

            cards += `<div class="card" data-artist="${artistId}">
                <h2>${artist}</h2>
                <div class="player-container" id="player_${artistId}" data-track="${firstTrack}"></div>
                ${trackButtons}
            </div>`;
        }

        return `<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vibe Recommendations</title>
<style>
* { box-sizing: border-box; }
body { 
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
    max-width: 1200px; margin: 0 auto; padding: 20px; 
    background: #0e1117; color: #fafafa;
}
h1 { color: #fafafa; border-bottom: 2px solid #1db954; padding-bottom: 10px; }
.input { 
    background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; 
    margin-bottom: 20px; border-left: 4px solid #1db954;
}
.grid { 
    display: grid; 
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); 
    gap: 20px; 
}
.card { 
    background: rgba(255,255,255,0.03); 
    padding: 20px; border-radius: 12px; 
    border: 1px solid rgba(255,255,255,0.1);
}
.card h2 { color: #fafafa; margin: 0 0 15px 0; font-size: 1.2rem; }
.player-container { 
    background: rgba(0,0,0,0.3); 
    border-radius: 12px; 
    min-height: 80px; 
    margin-bottom: 10px;
}
.track-btn {
    display: block; width: 100%; padding: 10px 12px;
    margin: 4px 0; border: none; border-radius: 8px;
    background: rgba(255,255,255,0.05); color: #fafafa;
    text-align: left; cursor: pointer; font-size: 14px;
    transition: background 0.2s;
}
.track-btn:hover { background: rgba(29, 185, 84, 0.2); }
.track-btn.active { background: rgba(29, 185, 84, 0.3); border-left: 3px solid #1db954; }
</style>
</head><body>
<h1>🎵 Vibe Recommendations</h1>
<div class="input"><strong>Based on:</strong> ${inputArtists}</div>
<div class="grid">${cards}</div>
${"<"}script src="https://open.spotify.com/embed/iframe-api/v1" async>${"<"}/script>
${"<"}script>
const controllers = {};

window.onSpotifyIframeApiReady = (IFrameAPI) => {
    document.querySelectorAll('.player-container').forEach(container => {
        const artistId = container.id.replace('player_', '');
        const trackId = container.dataset.track;
        
        IFrameAPI.createController(container, {
            width: '100%',
            height: '80',
            uri: trackId ? 'spotify:track:' + trackId : ''
        }, (controller) => {
            controllers[artistId] = controller;
        });
    });
};

let currentArtist = null;

function playTrack(btn, trackId) {
    const card = btn.closest('.card');
    const artistId = card.dataset.artist;
    
    if (currentArtist && currentArtist !== artistId && controllers[currentArtist]) {
        controllers[currentArtist].pause();
    }
    
    if (controllers[artistId]) {
        controllers[artistId].loadUri('spotify:track:' + trackId);
        controllers[artistId].play();
        currentArtist = artistId;
        card.querySelectorAll('.track-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    }
}
${"<"}/script>
</body></html>`;
    }

    function downloadHTML() {
        const html = generateHTML();
        const blob = new Blob([html], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "vibe-recommendations.html";
        a.click();
        URL.revokeObjectURL(url);
    }

    function downloadJSON() {
        const data = Object.entries($recommendations).map(
            ([artist, tracks]) => ({
                artist,
                tracks: tracks.map((t) => t.track_name),
            }),
        );
        const blob = new Blob([JSON.stringify(data, null, 2)], {
            type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "vibe-recommendations.json";
        a.click();
        URL.revokeObjectURL(url);
    }
</script>

<svelte:head>
    <link rel="preload" as="image" href={bgDark} />
    <link rel="preload" as="image" href={bgLight} />
</svelte:head>

{#if !$hasResults}
    <!-- Landing -->
    <div class="landing">
        {#if $settings.showBackground}
            <div class="bg-image"></div>
            <div class="bg-fade"></div>
        {/if}

        <div class="hero">
            <h1>Discover your next<br />favourite artist</h1>
            <p class="tagline">
                Music recommendations based on what you already love
            </p>

            <div class="search-row">
                <ArtistSelect
                    {selected}
                    onchange={(a) => (selected = a)}
                    max={LIMITS.MAX_INPUT_ARTISTS}
                    placeholder="Search artists..."
                />
                <button
                    class="btn-go"
                    onclick={search}
                    disabled={!selected.length || $isLoading}
                >
                    {$isLoading ? "..." : "Go"}
                </button>
            </div>

            {#if atMaxArtists}
                <p class="limit-msg">
                    Maximum {LIMITS.MAX_INPUT_ARTISTS} artists reached
                </p>
            {/if}

            {#if $isLoading}
                <div class="loading-bar">
                    <div
                        class="loading-fill"
                        style:width="{loadingProgress}%"
                    ></div>
                </div>
            {/if}

            {#if selected.length > 0}
                <div class="fine-section">
                    <div class="fine-row">
                        <span class="fine-label">Fine-tune:</span>
                        {#each selected as artist (artist)}
                            <button
                                class="fine-btn"
                                class:open={heroExpandedArtist === artist}
                                onclick={() => toggleHeroExpanded(artist)}
                            >
                                {artist}
                                {#if (fineTune[artist]?.length || 0) > 0}
                                    <span class="badge"
                                        >{fineTune[artist].length}</span
                                    >
                                {/if}
                            </button>
                        {/each}
                    </div>

                    {#if heroExpandedArtist}
                        <div class="songs-box">
                            <div class="songs-header">
                                <span class="songs-title"
                                    >{heroExpandedArtist}</span
                                >
                            </div>
                            <div class="songs-scroll">
                                {#each artistTracks[heroExpandedArtist] || [] as t (t.track_id)}
                                    {@const sel = (
                                        fineTune[heroExpandedArtist] || []
                                    ).includes(t.track_name)}
                                    {@const atLimit =
                                        isAtSongLimit(heroExpandedArtist)}
                                    <button
                                        class="song-chip"
                                        class:on={sel}
                                        class:disabled={!sel && atLimit}
                                        onclick={() =>
                                            toggleSong(
                                                heroExpandedArtist!,
                                                t.track_name,
                                            )}
                                        title={!sel && atLimit
                                            ? `Max ${LIMITS.MAX_INPUT_SONGS_PER_ARTIST} songs per artist`
                                            : ""}
                                    >
                                        {t.track_name.length > 35
                                            ? t.track_name.slice(0, 35) + "…"
                                            : t.track_name}
                                    </button>
                                {/each}
                                {#if !artistTracks[heroExpandedArtist]}
                                    <span class="muted">Loading...</span>
                                {/if}
                            </div>
                            {#if isAtSongLimit(heroExpandedArtist)}
                                <div class="limit-indicator">
                                    {fineTune[heroExpandedArtist]
                                        .length}/{LIMITS.MAX_INPUT_SONGS_PER_ARTIST}
                                    songs selected
                                </div>
                            {/if}
                        </div>
                    {/if}
                </div>
            {/if}

            {#if error}
                <p class="error">{error}</p>
            {/if}
        </div>
    </div>
{:else}
    <!-- Results -->
    <div class="results-wrap" class:right-open={$rightPanelOpen}>
        <aside class="side left">
            <h3>Search</h3>
            <div class="side-search">
                <ArtistSelect
                    {selected}
                    onchange={(a) => (selected = a)}
                    max={LIMITS.MAX_INPUT_ARTISTS}
                    placeholder="Add artists..."
                />
            </div>
            {#if atMaxArtists}
                <span class="side-limit"
                    >Max {LIMITS.MAX_INPUT_ARTISTS} artists</span
                >
            {/if}
            <button
                class="btn-update"
                onclick={search}
                disabled={!selected.length || $isLoading}
            >
                {$isLoading ? "Updating..." : "Update"}
            </button>

            {#if selected.length > 0}
                <div class="side-section fine-tune-section">
                    <div class="fine-header">
                        <h4>Fine-tune</h4>
                        <input
                            type="text"
                            class="side-song-search"
                            placeholder="Search songs..."
                            bind:value={globalSongSearch}
                        />
                    </div>
                    <div class="fine-tune-artists">
                        {#each selected as artist (artist)}
                            <div class="side-artist">
                                <button
                                    class="side-artist-btn"
                                    class:open={expandedArtists.has(artist)}
                                    onclick={() => toggleExpanded(artist)}
                                >
                                    <span class="name">{artist}</span>
                                    {#if (fineTune[artist]?.length || 0) > 0}
                                        <span class="cnt"
                                            >{fineTune[artist].length}</span
                                        >
                                    {/if}
                                    <span class="arr"
                                        >{expandedArtists.has(artist)
                                            ? "▾"
                                            : "▸"}</span
                                    >
                                </button>

                                {#if expandedArtists.has(artist)}
                                    <div class="side-songs">
                                        {#each getFilteredTracks(artist, globalSongSearch) as t (t.track_id)}
                                            {@const sel = (
                                                fineTune[artist] || []
                                            ).includes(t.track_name)}
                                            {@const atLimit =
                                                isAtSongLimit(artist)}
                                            <button
                                                class="ss"
                                                class:on={sel}
                                                class:disabled={!sel && atLimit}
                                                onclick={() =>
                                                    toggleSong(
                                                        artist,
                                                        t.track_name,
                                                    )}
                                            >
                                                {t.track_name.length > 26
                                                    ? t.track_name.slice(
                                                          0,
                                                          26,
                                                      ) + "…"
                                                    : t.track_name}
                                            </button>
                                        {/each}
                                        {#if getFilteredTracks(artist, globalSongSearch).length === 0 && globalSongSearch}
                                            <span class="muted">No matches</span
                                            >
                                        {/if}
                                    </div>
                                {/if}
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            <div class="side-section customize-section">
                <h4>Customize Your Vibe</h4>
                <div class="setting-group">
                    <label for="variety">
                        <span>Variety</span>
                        <span class="val">
                            {#if $settings.variety === 1}Low
                            {:else if $settings.variety === 2}Med
                            {:else}High{/if}
                        </span>
                    </label>
                    <input
                        id="variety"
                        type="range"
                        min="1"
                        max="3"
                        bind:value={$settings.variety}
                    />
                </div>

                <div class="setting-group">
                    <label for="genre">
                        <span>Genre Match</span>
                        <span class="val">{$settings.genreWeight}</span>
                    </label>
                    <input
                        id="genre"
                        type="range"
                        min="0"
                        max="5"
                        step="0.5"
                        bind:value={$settings.genreWeight}
                    />
                </div>

                <div class="setting-group">
                    <label for="count">
                        <span>Result Artists</span>
                        <span class="val">{$settings.maxResults}</span>
                    </label>
                    <input
                        id="count"
                        type="range"
                        min={LIMITS.MAX_RESULT_ARTISTS.min}
                        max={LIMITS.MAX_RESULT_ARTISTS.max}
                        bind:value={$settings.maxResults}
                    />
                </div>

                <div class="setting-group">
                    <label for="tracks">
                        <span>Songs per artist</span>
                        <span class="val">{$settings.tracksPerArtist}</span>
                    </label>
                    <input
                        id="tracks"
                        type="range"
                        min={LIMITS.MAX_TRACKS_PER_ARTIST.min}
                        max={LIMITS.MAX_TRACKS_PER_ARTIST.max}
                        bind:value={$settings.tracksPerArtist}
                    />
                </div>
            </div>
        </aside>

        <section class="main-results">
            <div class="results-header">
                <h2>{Object.keys($recommendations).length} artists for you</h2>
                <div class="results-actions">
                    <button
                        class="btn-action"
                        onclick={downloadHTML}
                        title="Download as HTML with Spotify players"
                    >
                        <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <path
                                d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"
                            />
                        </svg>
                        HTML
                    </button>
                    <button
                        class="btn-action"
                        onclick={downloadJSON}
                        title="Download as JSON"
                    >
                        <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <path
                                d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"
                            />
                        </svg>
                        JSON
                    </button>
                    <button
                        class="btn-action"
                        onclick={search}
                        disabled={$isLoading}
                    >
                        <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <path d="M23 4v6h-6M1 20v-6h6" />
                            <path
                                d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"
                            />
                        </svg>
                        Regenerate
                    </button>
                    <button
                        class="btn-action btn-panel-toggle"
                        onclick={() => rightPanelOpen.update((v) => !v)}
                        title={$rightPanelOpen ? "Hide lists" : "Show lists"}
                    >
                        <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <rect x="3" y="3" width="18" height="18" rx="2" />
                            <path d="M15 3v18" />
                        </svg>
                    </button>
                </div>
            </div>
            <div class="grid">
                {#each Object.entries($recommendations) as [artist, tracks] (artist)}
                    <ArtistCard
                        {artist}
                        {tracks}
                        onAddToKnown={() => addToKnown(artist)}
                        onAddToSearch={() => addToSearch(artist)}
                        onAddFavorite={(track) => addFavorite(track, artist)}
                        isKnown={$knownArtists.includes(artist)}
                    />
                {/each}
            </div>
        </section>

        <!-- Mobile sidebar toggle button -->
        <button
            class="mobile-sidebar-toggle"
            onclick={() => mobileSidebarOpen.update((v) => !v)}
            title="Toggle favourites"
        >
            {#if $mobileSidebarOpen}
                ✕
            {:else}
                ♥ <span class="toggle-badge">{$favoriteTracks.length}</span>
            {/if}
        </button>

        {#if $mobileSidebarOpen}
            <button
                class="sidebar-backdrop"
                onclick={() => mobileSidebarOpen.set(false)}
                aria-label="Close sidebar"
            ></button>
        {/if}

        {#if $rightPanelOpen || $mobileSidebarOpen}
            <aside class="side right" class:mobile-open={$mobileSidebarOpen}>
                <button
                    class="mobile-close-btn"
                    onclick={() => mobileSidebarOpen.set(false)}
                >
                    ✕
                </button>
                <div class="side-section">
                    <h4>
                        Known Artists <span class="cnt-badge"
                            >{$knownArtists.length}</span
                        >
                    </h4>
                    <p class="side-hint">Won't be recommended</p>
                    {#if $knownArtists.length === 0}
                        <p class="side-empty">No artists added yet</p>
                    {:else}
                        <div class="known-chips">
                            {#each $knownArtists as artist (artist)}
                                <button
                                    class="known-chip"
                                    onclick={() => removeFromKnown(artist)}
                                    title="Remove {artist}"
                                >
                                    {artist} <span class="x">×</span>
                                </button>
                            {/each}
                        </div>
                    {/if}
                </div>

                <div class="side-section favorites-section">
                    <h4>
                        Favourites <span class="cnt-badge"
                            >{$favoriteTracks.length}</span
                        >
                    </h4>
                    {#if $favoriteTracks.length === 0}
                        <p class="side-empty">No favourites yet</p>
                    {:else}
                        <div class="favorites-grouped">
                            {#each Object.entries(favoritesByArtist) as [artist, tracks] (artist)}
                                <div class="fav-group">
                                    <span class="fav-artist-name">{artist}</span
                                    >
                                    {#each tracks as fav (fav.track_id)}
                                        <div
                                            class="fav-track-row"
                                            class:playing={$sidebarPlaying?.trackId ===
                                                fav.track_id}
                                            role="button"
                                            tabindex="0"
                                            onclick={() => playTrack(fav)}
                                            onkeydown={(e) =>
                                                e.key === "Enter" &&
                                                playTrack(fav)}
                                        >
                                            <span class="fav-track-name"
                                                >{fav.track_name}</span
                                            >
                                            <button
                                                class="fav-remove"
                                                onclick={(e) => {
                                                    e.stopPropagation();
                                                    removeFavorite(
                                                        fav.track_id,
                                                    );
                                                }}>×</button
                                            >
                                        </div>
                                    {/each}
                                </div>
                            {/each}
                        </div>
                    {/if}
                </div>

                {#if $sidebarPlaying}
                    <div class="player-section">
                        <div class="player-info">
                            <span class="player-track"
                                >{$sidebarPlaying.trackName}</span
                            >
                            <span class="player-artist"
                                >{$sidebarPlaying.artist}</span
                            >
                        </div>
                    </div>
                {/if}
                <!-- Hidden player - always mounted for audio -->
                <div class="player-embed-wrap hidden">
                    <div
                        class="sidebar-player"
                        bind:this={sidebarPlayerEl}
                    ></div>
                </div>
            </aside>
        {/if}
    </div>
{/if}

<style>
    /* Landing */
    .landing {
        flex: 1;
        display: flex;
        position: relative;
        overflow: hidden;
    }

    .bg-image {
        position: absolute;
        inset: 0;
        pointer-events: none;
        background: url("$lib/assets/background_dark.webp") center center
            no-repeat;
        background-size: 1920px auto;
        opacity: 0.06;
        filter: blur(2px) saturate(2);
    }

    @media (prefers-color-scheme: light) {
        .bg-image {
            background-image: url("$lib/assets/background_light.webp");
        }
    }

    :global([data-theme="light"]) .bg-image {
        background-image: url("$lib/assets/background_light.webp");
    }

    :global([data-theme="dark"]) .bg-image {
        background-image: url("$lib/assets/background_dark.webp");
        opacity: 0.12;
    }

    .bg-fade {
        position: absolute;
        inset: 0;
        pointer-events: none;
        background: radial-gradient(
            ellipse 60% 60% at center,
            var(--bg) 0%,
            var(--bg) 20%,
            transparent 80%
        );
    }

    .hero {
        position: relative;
        z-index: 1;
        width: 100%;
        max-width: 560px;
        margin: 0 auto;
        padding: 25vh 1.5rem 2rem;
        text-align: center;
    }

    .hero h1 {
        font-size: clamp(1.6rem, 4.5vw, 2.4rem);
        font-weight: 800;
        line-height: 1.15;
        letter-spacing: -0.5px;
        margin-bottom: 0.5rem;
    }

    .tagline {
        color: var(--text-2);
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }

    .search-row {
        display: flex;
        gap: 0.5rem;
        justify-content: center;
    }

    .btn-go {
        padding: 0 1.25rem;
        background: var(--gold);
        color: #111;
        font-weight: 600;
        font-size: 0.9rem;
        border: none;
        border-radius: 8px;
        white-space: nowrap;
    }

    .btn-go:hover:not(:disabled) {
        filter: brightness(1.1);
    }

    .btn-go:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .limit-msg {
        margin-top: 0.5rem;
        font-size: 0.75rem;
        color: var(--gold);
    }

    .loading-bar {
        margin-top: 1rem;
        height: 3px;
        background: var(--border);
        border-radius: 2px;
        overflow: hidden;
    }

    .loading-fill {
        height: 100%;
        background: linear-gradient(90deg, var(--gold), var(--gold-dim));
        transition: width 0.15s ease-out;
    }

    .fine-section {
        margin-top: 1rem;
    }

    .fine-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: center;
        gap: 0.35rem;
        margin-bottom: 0.75rem;
    }

    .fine-label {
        font-size: 0.75rem;
        color: var(--text-3);
        margin-right: 0.25rem;
    }

    .fine-btn {
        padding: 0.25rem 0.5rem;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 4px;
        font-size: 0.75rem;
        color: var(--text-2);
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
    }

    .fine-btn:hover,
    .fine-btn.open {
        border-color: var(--gold);
        color: var(--text);
    }

    .badge {
        background: var(--gold);
        color: #111;
        font-size: 0.6rem;
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-weight: 600;
    }

    .songs-box {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 0.5rem;
        margin-bottom: 0.75rem;
    }

    .songs-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
    }

    .songs-title {
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--text);
    }

    .songs-scroll {
        display: flex;
        flex-wrap: wrap;
        gap: 0.3rem;
        max-height: 140px;
        overflow-y: auto;
    }

    .song-chip {
        padding: 0.2rem 0.45rem;
        background: var(--bg-alt);
        border: 1px solid transparent;
        border-radius: 4px;
        font-size: 0.7rem;
        color: var(--text-2);
    }

    .song-chip:hover:not(.disabled) {
        border-color: var(--border);
    }

    .song-chip.on {
        background: var(--gold);
        color: #111;
    }

    .song-chip.disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    .limit-indicator {
        margin-top: 0.4rem;
        font-size: 0.65rem;
        color: var(--gold);
        text-align: right;
    }

    .muted {
        font-size: 0.7rem;
        color: var(--text-3);
    }

    .error {
        padding: 0.5rem;
        background: rgba(220, 60, 60, 0.1);
        border-radius: 6px;
        color: #e55;
        font-size: 0.8rem;
    }

    /* Results */
    .results-wrap {
        flex: 1;
        display: grid;
        grid-template-columns: 260px 1fr;
        overflow: hidden;
    }

    .results-wrap.right-open {
        grid-template-columns: 260px 1fr 280px;
    }

    .side {
        background: var(--surface);
        border-right: 1px solid var(--border);
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        height: calc(100vh - 52px);
        position: sticky;
        top: 52px;
    }

    .side.left {
        overflow: hidden;
    }

    .fine-tune-section {
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .fine-tune-artists {
        flex: 1;
        overflow-y: auto;
        min-height: 0;
    }

    .customize-section {
        flex-shrink: 0;
    }

    .side.right {
        border-right: none;
        border-left: 1px solid var(--border);
    }

    .side h3 {
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--text);
    }

    .side-search {
        position: relative;
        z-index: 50;
    }

    .side-limit {
        font-size: 0.7rem;
        color: var(--gold);
    }

    .btn-update {
        padding: 0.55rem;
        background: var(--gold);
        color: #111;
        font-weight: 600;
        font-size: 0.8rem;
        border: none;
        border-radius: 6px;
    }

    .btn-update:disabled {
        opacity: 0.5;
    }

    .side-section {
        border-top: 1px solid var(--border);
        padding-top: 0.75rem;
    }

    .side-section h4 {
        font-size: 0.65rem;
        font-weight: 600;
        color: var(--text-3);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .fine-tune-artists {
        max-height: 50vh;
        overflow-y: auto;
    }

    .cnt-badge {
        background: var(--bg-alt);
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
        font-size: 0.6rem;
    }

    .side-hint {
        font-size: 0.65rem;
        color: var(--text-3);
        margin-bottom: 0.5rem;
    }

    .side-empty {
        font-size: 0.75rem;
        color: var(--text-3);
        font-style: italic;
    }

    .side-artist {
        margin-bottom: 0.4rem;
    }

    .side-artist-btn {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.45rem 0.5rem;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 5px;
        font-size: 0.8rem;
        color: var(--text);
        text-align: left;
    }

    .side-artist-btn .name {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .side-artist-btn .cnt {
        background: var(--gold);
        color: #111;
        font-size: 0.6rem;
        padding: 0.1rem 0.25rem;
        border-radius: 3px;
        font-weight: 600;
    }

    .side-artist-btn .arr {
        color: var(--text-3);
        font-size: 0.65rem;
    }

    .side-artist-btn:hover,
    .side-artist-btn.open {
        border-color: var(--gold);
    }

    .side-songs {
        margin-top: 0.35rem;
        max-height: 200px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
        padding-left: 0.4rem;
    }

    .side-song-search {
        padding: 0.3rem 0.4rem;
        font-size: 0.7rem;
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: 4px;
        color: var(--text);
        margin-bottom: 0.2rem;
        max-width: 140px;
    }

    .side-song-search:focus {
        outline: none;
        border-color: white;
    }

    .side-song-search::placeholder {
        color: var(--text-3);
    }

    .ss {
        padding: 0.3rem 0.4rem;
        background: var(--bg);
        border: 1px solid transparent;
        border-radius: 4px;
        font-size: 0.7rem;
        color: var(--text-2);
        text-align: left;
    }

    .ss:hover:not(.disabled) {
        border-color: var(--border);
    }

    .ss.on {
        background: var(--gold);
        color: #111;
        border-color: var(--gold);
    }

    .ss.disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    .main-results {
        padding: 1.25rem;
        overflow-y: auto;
        max-height: calc(100vh - 52px);
    }

    .results-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 1rem;
        flex-wrap: wrap;
        gap: 0.5rem;
    }

    .results-header h2 {
        font-size: 0.95rem;
        font-weight: 500;
        color: var(--text-2);
    }

    .results-actions {
        display: flex;
        gap: 0.5rem;
    }

    .btn-action {
        display: flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.4rem 0.65rem;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 5px;
        font-size: 0.75rem;
        color: var(--text-2);
    }

    .btn-action:hover:not(:disabled) {
        border-color: var(--gold);
        color: var(--text);
    }

    .btn-action:disabled {
        opacity: 0.5;
    }

    .btn-action svg {
        width: 14px;
        height: 14px;
    }

    .btn-panel-toggle {
        padding: 0.4rem;
    }

    .btn-panel-toggle svg {
        width: 16px;
        height: 16px;
    }

    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
        gap: 1rem;
    }

    /* Right panel lists */
    .known-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.3rem;
    }

    .known-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.2rem 0.4rem;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 4px;
        font-size: 0.7rem;
        color: var(--text);
        max-width: 140px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .known-chip:hover {
        border-color: #e55;
    }

    .known-chip .x {
        color: var(--text-3);
        font-size: 0.8rem;
    }

    .known-chip:hover .x {
        color: #e55;
    }

    .favorites-section {
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
    }

    .favorites-grouped {
        flex: 1;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .fav-group {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
    }

    .fav-artist-name {
        font-size: 0.7rem;
        font-weight: 600;
        color: var(--gold);
        margin-bottom: 0.15rem;
    }

    .fav-track-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.35rem 0.5rem;
        background: var(--bg-alt);
        border-radius: 4px;
        margin-left: 0.5rem;
        cursor: pointer;
        transition: background 0.15s;
    }

    .fav-track-name {
        font-size: 0.75rem;
        color: var(--text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: 1;
        min-width: 0;
    }

    .fav-remove {
        background: none;
        border: none;
        color: var(--text-3);
        font-size: 0.9rem;
        padding: 0;
        line-height: 1;
        flex-shrink: 0;
    }

    .fav-remove:hover {
        color: #e55;
    }

    .fav-track-row:hover {
        background: var(--border);
    }

    .fav-track-row.playing {
        background: var(--gold);
        color: #111;
    }

    .fav-track-row.playing .fav-track-name {
        color: #111;
    }

    .fav-track-row.playing .fav-remove {
        color: #333;
    }

    .fav-track-row.playing .fav-remove:hover {
        color: #900;
    }

    .player-section {
        flex-shrink: 0;
        border-top: 1px solid var(--border);
        padding-top: 0.75rem;
        margin-top: auto;
    }

    .player-info {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
        flex: 1;
        min-width: 0;
    }

    .player-track {
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .player-artist {
        font-size: 0.65rem;
        color: var(--text-3);
    }

    .player-embed-wrap {
        position: relative;
        height: 80px;
        border-radius: 10px;
        overflow: hidden;
        background: #121212;
    }

    .player-embed-wrap.hidden {
        height: 0;
        overflow: hidden;
        position: absolute;
        opacity: 0;
        pointer-events: none;
    }

    .sidebar-player {
        position: absolute;
        inset: 0;
    }

    .sidebar-player :global(iframe) {
        border: none !important;
        border-radius: 10px !important;
        width: 100% !important;
        height: 80px !important;
    }

    /* Mobile sidebar toggle */
    .mobile-sidebar-toggle {
        display: none;
        position: fixed;
        right: 1rem;
        bottom: 1rem;
        z-index: 250;
        width: 48px;
        height: 48px;
        border-radius: 50%;
        background: var(--gold);
        color: #111;
        border: none;
        font-size: 1.1rem;
        box-shadow: 0 4px 12px var(--shadow);
        align-items: center;
        justify-content: center;
    }

    .toggle-badge {
        position: absolute;
        top: -4px;
        right: -4px;
        background: #e55;
        color: #fff;
        font-size: 0.6rem;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .sidebar-backdrop {
        display: none;
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        z-index: 290;
        border: none;
        cursor: pointer;
    }

    .mobile-close-btn {
        display: none;
        position: absolute;
        top: 0.5rem;
        right: 0.5rem;
        width: 28px;
        height: 28px;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 50%;
        color: var(--text-2);
        font-size: 0.9rem;
        align-items: center;
        justify-content: center;
        z-index: 10;
    }

    .mobile-close-btn:hover {
        background: var(--border);
        color: var(--text);
    }

    .fine-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
    }

    .fine-header h4 {
        margin: 0;
    }

    @media (max-width: 1024px) {
        .results-wrap.right-open {
            grid-template-columns: 260px 1fr;
        }

        /* Hide sidebar on tablet/mobile by default, show toggle button */
        .side.right {
            display: none;
        }

        .side.right.mobile-open {
            display: flex;
            position: fixed;
            top: 0;
            right: 0;
            bottom: 0;
            left: auto;
            width: 280px;
            max-width: 85vw;
            height: 100vh;
            max-height: none;
            border-left: 1px solid var(--border);
            border-radius: 0;
            z-index: 300;
            box-shadow: -4px 0 20px var(--shadow);
            animation: slideIn 0.2s ease-out;
        }

        .mobile-sidebar-toggle {
            display: flex;
        }

        .sidebar-backdrop {
            display: block;
        }

        .mobile-close-btn {
            display: flex;
        }

        .btn-panel-toggle {
            display: none;
        }
    }

    @keyframes slideIn {
        from {
            transform: translateX(100%);
        }
        to {
            transform: translateX(0);
        }
    }

    @media (max-width: 768px) {
        .results-wrap,
        .results-wrap.right-open {
            grid-template-columns: 1fr;
        }

        .side.left {
            position: relative;
            top: 0;
            height: auto;
            max-height: 300px;
            border-right: none;
            border-bottom: 1px solid var(--border);
            z-index: 100;
        }

        .fine-tune-section {
            z-index: 50;
        }

        .side-songs {
            z-index: 60;
            position: relative;
        }

        .search-row {
            flex-direction: column;
        }

        .btn-go {
            padding: 0.6rem;
        }

        .grid {
            grid-template-columns: 1fr;
        }

        .main-results {
            max-height: none;
            padding-bottom: 80px;
        }
    }
    .setting-group {
        margin-bottom: 0.8rem;
    }

    .setting-group label {
        display: flex;
        justify-content: space-between;
        font-size: 0.75rem;
        color: var(--text-2);
        margin-bottom: 0.3rem;
    }

    .setting-group .val {
        color: var(--gold);
        font-weight: 600;
        font-size: 0.7rem;
    }

    .setting-group input[type="range"] {
        width: 100%;
        height: 4px;
        background: var(--bg-alt);
        border-radius: 2px;
        appearance: none;
        outline: none;
    }

    .setting-group input[type="range"]::-webkit-slider-thumb {
        appearance: none;
        width: 14px;
        height: 14px;
        background: var(--gold);
        border-radius: 50%;
        cursor: pointer;
        border: 2px solid var(--surface);
    }
</style>
