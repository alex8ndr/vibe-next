<script lang="ts">
    import { onMount } from "svelte";
    import ArtistSelect from "$lib/components/ArtistSelect.svelte";
    import ArtistCard from "$lib/components/ArtistCard.svelte";
    import {
        fetchArtists,
        fetchRecommendations,
        fetchArtistTracks,
    } from "$lib/api";
    import {
        artistsList,
        recommendations,
        isLoading,
        hasResults,
        type Track,
    } from "$lib/stores";

    let selected = $state<string[]>([]);
    let fineTune = $state<Record<string, string[]>>({});
    let artistTracks = $state<Record<string, Track[]>>({});
    let expandedArtists = $state<Record<string, boolean>>({});
    let searchQueries = $state<Record<string, string>>({});
    let error = $state<string | null>(null);
    let showFineTune = $state(false);

    onMount(async () => {
        // Set up Spotify IFrame API
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
        } catch (e) {
            error = "Could not connect to server";
        }
    });

    async function loadTracksFor(artist: string) {
        if (artistTracks[artist]) return;
        try {
            const tracks = await fetchArtistTracks(artist);
            artistTracks = { ...artistTracks, [artist]: tracks };
        } catch {
            // silently fail
        }
    }

    $effect(() => {
        selected.forEach((a) => loadTracksFor(a));
    });

    async function search() {
        if (selected.length === 0) return;

        error = null;
        isLoading.set(true);

        const trackIds: string[] = [];
        for (const artist of selected) {
            const songs = fineTune[artist];
            if (songs?.length > 0) {
                const tracks = artistTracks[artist] || [];
                songs.forEach((name) => {
                    const t = tracks.find((tr) => tr.track_name === name);
                    if (t) trackIds.push(t.track_id);
                });
            }
        }

        try {
            const result = await fetchRecommendations({
                artists: selected,
                track_ids: trackIds.length > 0 ? trackIds : undefined,
                diversity: 2,
                max_artists: 6,
            });
            recommendations.set(result.recommendations);
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
        } finally {
            isLoading.set(false);
        }
    }

    function handleArtistsChange(artists: string[]) {
        selected = artists;
        const kept: Record<string, string[]> = {};
        artists.forEach((a) => {
            if (fineTune[a]) kept[a] = fineTune[a];
        });
        fineTune = kept;
    }

    function toggleSong(artist: string, song: string) {
        const current = fineTune[artist] || [];
        if (current.includes(song)) {
            fineTune = {
                ...fineTune,
                [artist]: current.filter((s) => s !== song),
            };
        } else if (current.length < 3) {
            fineTune = { ...fineTune, [artist]: [...current, song] };
        }
    }

    function getFilteredTracks(artist: string): Track[] {
        const all = artistTracks[artist] || [];
        const query = (searchQueries[artist] || "").toLowerCase();
        const isExpanded = expandedArtists[artist];

        let filtered = query
            ? all.filter((t) => t.track_name.toLowerCase().includes(query))
            : all;
        return isExpanded ? filtered : filtered.slice(0, 8);
    }

    function toggleExpand(artist: string) {
        expandedArtists = {
            ...expandedArtists,
            [artist]: !expandedArtists[artist],
        };
    }

    function updateSearch(artist: string, value: string) {
        searchQueries = { ...searchQueries, [artist]: value };
    }
</script>

<div class="page">
    <header class="header">
        <div class="container">
            <h1 class="logo">Vibe</h1>
            {#if !$hasResults}
                <p class="tagline">Discover music based on artists you love</p>
            {/if}
        </div>
    </header>

    <section class="search-section">
        <div class="container">
            <div class="search-row">
                <div class="select-wrapper">
                    <ArtistSelect
                        {selected}
                        onchange={handleArtistsChange}
                        max={5}
                        placeholder="Search for artists..."
                    />
                </div>

                <button
                    class="btn"
                    onclick={search}
                    disabled={selected.length === 0 || $isLoading}
                >
                    {$isLoading ? "Searching..." : "Find Music"}
                </button>
            </div>

            {#if selected.length > 0}
                <button
                    class="toggle-fine"
                    onclick={() => (showFineTune = !showFineTune)}
                >
                    {showFineTune ? "− Hide" : "+ Fine-tune"} with specific songs
                </button>

                {#if showFineTune}
                    <div class="fine-tune">
                        {#each selected as artist (artist)}
                            {@const tracks = artistTracks[artist] || []}
                            {@const filtered = getFilteredTracks(artist)}
                            {@const isExpanded = expandedArtists[artist]}
                            {@const hasMore = tracks.length > 8}

                            <div class="fine-artist">
                                <div class="fine-header">
                                    <strong>{artist}</strong>
                                    {#if hasMore}
                                        <input
                                            type="text"
                                            class="track-search"
                                            placeholder="Search songs..."
                                            value={searchQueries[artist] || ""}
                                            oninput={(e) =>
                                                updateSearch(
                                                    artist,
                                                    e.currentTarget.value,
                                                )}
                                        />
                                    {/if}
                                </div>

                                <div class="song-chips">
                                    {#if tracks.length > 0}
                                        {#each filtered as track (track.track_id)}
                                            {@const isSelected = (
                                                fineTune[artist] || []
                                            ).includes(track.track_name)}
                                            <button
                                                class="chip"
                                                class:selected={isSelected}
                                                onclick={() =>
                                                    toggleSong(
                                                        artist,
                                                        track.track_name,
                                                    )}
                                            >
                                                {track.track_name.length > 30
                                                    ? track.track_name.slice(
                                                          0,
                                                          30,
                                                      ) + "…"
                                                    : track.track_name}
                                            </button>
                                        {/each}

                                        {#if hasMore && !searchQueries[artist]}
                                            <button
                                                class="chip show-more"
                                                onclick={() =>
                                                    toggleExpand(artist)}
                                            >
                                                {isExpanded
                                                    ? "Show less"
                                                    : `+${tracks.length - 8} more`}
                                            </button>
                                        {/if}
                                    {:else}
                                        <span class="loading-text"
                                            >Loading...</span
                                        >
                                    {/if}
                                </div>
                            </div>
                        {/each}
                    </div>
                {/if}
            {/if}

            {#if error}
                <p class="error">{error}</p>
            {/if}
        </div>
    </section>

    {#if $hasResults}
        <section class="results">
            <div class="container">
                <h2 class="results-title">
                    {Object.keys($recommendations).length} artists based on your
                    selection
                </h2>

                <div class="grid">
                    {#each Object.entries($recommendations) as [artist, tracks] (artist)}
                        <ArtistCard {artist} {tracks} />
                    {/each}
                </div>
            </div>
        </section>
    {/if}
</div>

<style>
    .page {
        min-height: 100vh;
        padding-bottom: 3rem;
    }

    .container {
        max-width: 1100px;
        margin: 0 auto;
        padding: 0 1.25rem;
    }

    .header {
        padding: 3rem 0 1.5rem;
    }

    .logo {
        font-size: 2.5rem;
        font-weight: 800;
        letter-spacing: -1px;
        background: linear-gradient(
            135deg,
            var(--gold) 0%,
            var(--gold-dim) 100%
        );
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }

    .tagline {
        margin-top: 0.5rem;
        color: var(--text-secondary);
        font-size: 1.1rem;
    }

    .search-section {
        padding: 1rem 0 2rem;
    }

    .search-row {
        display: flex;
        gap: 0.75rem;
        align-items: flex-start;
    }

    .select-wrapper {
        flex: 1;
    }

    .btn {
        padding: 0.7rem 1.25rem;
        background: var(--gold);
        color: #111;
        font-weight: 600;
        font-size: 0.9rem;
        border: none;
        border-radius: 8px;
        white-space: nowrap;
        transition:
            transform 0.15s,
            box-shadow 0.15s;
    }

    .btn:hover:not(:disabled) {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px var(--gold-glow);
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .toggle-fine {
        margin-top: 0.75rem;
        padding: 0.4rem 0;
        background: none;
        border: none;
        color: var(--text-muted);
        font-size: 0.85rem;
    }

    .toggle-fine:hover {
        color: var(--text-secondary);
    }

    .fine-tune {
        margin-top: 1rem;
        padding: 1rem;
        background: var(--bg-secondary);
        border-radius: 8px;
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
    }

    .fine-header {
        display: flex;
        align-items: center;
        gap: 1rem;
        margin-bottom: 0.5rem;
    }

    .fine-header strong {
        color: var(--text-primary);
        font-size: 0.9rem;
    }

    .track-search {
        flex: 1;
        max-width: 200px;
        padding: 0.35rem 0.6rem;
        background: var(--bg-input);
        border: 1px solid var(--border);
        border-radius: 4px;
        color: var(--text-primary);
        font-size: 0.8rem;
    }

    .track-search::placeholder {
        color: var(--text-muted);
    }

    .song-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
    }

    .chip {
        padding: 0.35rem 0.6rem;
        background: var(--bg-input);
        border: 1px solid var(--border);
        border-radius: 4px;
        color: var(--text-secondary);
        font-size: 0.8rem;
        cursor: pointer;
        transition: all 0.15s;
    }

    .chip:hover {
        border-color: var(--gold);
        color: var(--text-primary);
    }

    .chip.selected {
        background: var(--gold);
        border-color: var(--gold);
        color: #111;
    }

    .chip.show-more {
        background: transparent;
        border-style: dashed;
        color: var(--text-muted);
    }

    .chip.show-more:hover {
        color: var(--gold);
        border-color: var(--gold);
    }

    .loading-text {
        color: var(--text-muted);
        font-size: 0.8rem;
    }

    .error {
        margin-top: 1rem;
        padding: 0.75rem 1rem;
        background: hsla(0, 70%, 50%, 0.1);
        border: 1px solid hsla(0, 70%, 50%, 0.3);
        border-radius: 6px;
        color: hsl(0, 70%, 60%);
        font-size: 0.9rem;
    }

    .results {
        padding: 1rem 0;
    }

    .results-title {
        font-size: 1rem;
        font-weight: 500;
        color: var(--text-secondary);
        margin-bottom: 1.25rem;
    }

    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
        gap: 1.25rem;
    }

    @media (max-width: 640px) {
        .header {
            padding: 2rem 0 1rem;
        }

        .logo {
            font-size: 2rem;
        }

        .search-row {
            flex-direction: column;
        }

        .btn {
            width: 100%;
        }

        .grid {
            grid-template-columns: 1fr;
        }
    }
</style>
