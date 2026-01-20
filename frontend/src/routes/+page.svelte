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
    let expandedArtist = $state<string | null>(null);
    let error = $state<string | null>(null);

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
                diversity: 2,
                max_artists: 6,
            });
            recommendations.set(res.recommendations);
        } catch (e) {
            error = e instanceof Error ? e.message : "Search failed";
        } finally {
            isLoading.set(false);
        }
    }

    function toggleSong(artist: string, song: string) {
        const cur = fineTune[artist] || [];
        if (cur.includes(song)) {
            fineTune = { ...fineTune, [artist]: cur.filter((s) => s !== song) };
        } else if (cur.length < 3) {
            fineTune = { ...fineTune, [artist]: [...cur, song] };
        }
    }
</script>

{#if !$hasResults}
    <!-- Landing / Hero -->
    <div class="landing">
        <div class="bg-decor">
            {#each Array(8) as _, i}
                <div
                    class="fake-embed"
                    style="
						--x: {20 + (i % 4) * 22}%;
						--y: {30 + Math.floor(i / 4) * 35}%;
						--rot: {-15 + i * 4}deg;
						--scale: {0.6 + (i % 3) * 0.15};
						--delay: {i * 0.1}s;
					"
                ></div>
            {/each}
            <div class="gradient-overlay"></div>
        </div>

        <div class="hero">
            <h1>Discover your next<br />favorite artist</h1>
            <p class="sub">
                Music recommendations based on what you already love
            </p>

            <div class="search-box">
                <ArtistSelect
                    {selected}
                    onchange={(a) => (selected = a)}
                    max={5}
                    placeholder="Search artists..."
                />
                <button
                    class="btn-search"
                    onclick={search}
                    disabled={!selected.length || $isLoading}
                >
                    {$isLoading ? "Searching..." : "Find Music"}
                </button>
            </div>

            {#if selected.length > 0}
                <div class="fine-tune-section">
                    <span class="ft-label">Fine-tune:</span>
                    {#each selected as artist (artist)}
                        <button
                            class="ft-artist"
                            class:expanded={expandedArtist === artist}
                            onclick={() =>
                                (expandedArtist =
                                    expandedArtist === artist ? null : artist)}
                        >
                            {artist}
                            {#if (fineTune[artist]?.length || 0) > 0}
                                <span class="ft-count"
                                    >{fineTune[artist].length}</span
                                >
                            {/if}
                        </button>
                    {/each}
                </div>

                {#if expandedArtist}
                    <div class="song-picker">
                        <div class="song-list">
                            {#each artistTracks[expandedArtist] || [] as t (t.track_id)}
                                {@const sel = (
                                    fineTune[expandedArtist] || []
                                ).includes(t.track_name)}
                                <button
                                    class="song"
                                    class:selected={sel}
                                    onclick={() =>
                                        toggleSong(
                                            expandedArtist!,
                                            t.track_name,
                                        )}
                                >
                                    {t.track_name}
                                </button>
                            {/each}
                            {#if !artistTracks[expandedArtist]}
                                <span class="loading">Loading songs...</span>
                            {/if}
                        </div>
                    </div>
                {/if}
            {/if}

            {#if error}
                <p class="error">{error}</p>
            {/if}
        </div>
    </div>
{:else}
    <!-- Results Layout: Sidebar + Grid -->
    <div class="results-layout">
        <aside class="sidebar">
            <h3>Search</h3>
            <ArtistSelect
                {selected}
                onchange={(a) => (selected = a)}
                max={5}
                placeholder="Add artists..."
            />
            <button
                class="btn-search"
                onclick={search}
                disabled={!selected.length || $isLoading}
            >
                {$isLoading ? "Searching..." : "Update"}
            </button>

            {#if selected.length > 0}
                <div class="sidebar-section">
                    <h4>Fine-tune</h4>
                    {#each selected as artist (artist)}
                        <div class="sidebar-artist">
                            <button
                                class="sidebar-artist-btn"
                                class:expanded={expandedArtist === artist}
                                onclick={() =>
                                    (expandedArtist =
                                        expandedArtist === artist
                                            ? null
                                            : artist)}
                            >
                                <span>{artist}</span>
                                {#if (fineTune[artist]?.length || 0) > 0}
                                    <span class="count"
                                        >{fineTune[artist].length}</span
                                    >
                                {/if}
                                <span class="arrow"
                                    >{expandedArtist === artist
                                        ? "▾"
                                        : "▸"}</span
                                >
                            </button>

                            {#if expandedArtist === artist}
                                <div class="sidebar-songs">
                                    {#each artistTracks[artist] || [] as t (t.track_id)}
                                        {@const sel = (
                                            fineTune[artist] || []
                                        ).includes(t.track_name)}
                                        <button
                                            class="s-song"
                                            class:selected={sel}
                                            onclick={() =>
                                                toggleSong(
                                                    artist,
                                                    t.track_name,
                                                )}
                                        >
                                            {t.track_name.length > 28
                                                ? t.track_name.slice(0, 28) +
                                                  "…"
                                                : t.track_name}
                                        </button>
                                    {/each}
                                </div>
                            {/if}
                        </div>
                    {/each}
                </div>
            {/if}
        </aside>

        <section class="results">
            <h2>{Object.keys($recommendations).length} artists for you</h2>
            <div class="grid">
                {#each Object.entries($recommendations) as [artist, tracks] (artist)}
                    <ArtistCard {artist} {tracks} />
                {/each}
            </div>
        </section>
    </div>
{/if}

<style>
    /* Landing */
    .landing {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        overflow: hidden;
        padding: 2rem;
    }

    .bg-decor {
        position: absolute;
        inset: 0;
        pointer-events: none;
    }

    .fake-embed {
        position: absolute;
        left: var(--x);
        top: var(--y);
        width: 280px;
        height: 80px;
        background: linear-gradient(135deg, #282828 0%, #181818 100%);
        border-radius: 12px;
        transform: rotate(var(--rot)) scale(var(--scale));
        opacity: 0.4;
        animation: float 6s ease-in-out infinite;
        animation-delay: var(--delay);
    }

    @keyframes float {
        0%,
        100% {
            transform: rotate(var(--rot)) scale(var(--scale)) translateY(0);
        }
        50% {
            transform: rotate(var(--rot)) scale(var(--scale)) translateY(-10px);
        }
    }

    .gradient-overlay {
        position: absolute;
        inset: 0;
        background: linear-gradient(
            to bottom,
            var(--bg) 0%,
            transparent 30%,
            transparent 60%,
            var(--bg) 100%
        );
    }

    .hero {
        position: relative;
        z-index: 1;
        max-width: 560px;
        text-align: center;
    }

    .hero h1 {
        font-size: clamp(1.8rem, 5vw, 2.8rem);
        font-weight: 800;
        line-height: 1.2;
        letter-spacing: -1px;
        margin-bottom: 0.75rem;
    }

    .sub {
        color: var(--text-2);
        font-size: 1rem;
        margin-bottom: 2rem;
    }

    .search-box {
        display: flex;
        gap: 0.5rem;
        margin-bottom: 1rem;
    }

    .search-box :global(.wrapper) {
        flex: 1;
    }

    .btn-search {
        padding: 0.6rem 1.25rem;
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

    .btn-search:hover:not(:disabled) {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px var(--gold-glow);
    }

    .btn-search:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .fine-tune-section {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: center;
        gap: 0.4rem;
        margin-bottom: 0.75rem;
    }

    .ft-label {
        font-size: 0.8rem;
        color: var(--text-3);
    }

    .ft-artist {
        padding: 0.3rem 0.6rem;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 4px;
        font-size: 0.8rem;
        color: var(--text-2);
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
    }

    .ft-artist:hover,
    .ft-artist.expanded {
        border-color: var(--gold);
        color: var(--text);
    }

    .ft-count {
        background: var(--gold);
        color: #111;
        font-size: 0.65rem;
        padding: 0.1rem 0.35rem;
        border-radius: 3px;
        font-weight: 600;
    }

    .song-picker {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 0.5rem;
        margin-bottom: 1rem;
    }

    .song-list {
        display: flex;
        flex-wrap: wrap;
        gap: 0.3rem;
        max-height: 150px;
        overflow-y: auto;
    }

    .song {
        padding: 0.25rem 0.5rem;
        background: var(--bg-alt);
        border: 1px solid transparent;
        border-radius: 4px;
        font-size: 0.75rem;
        color: var(--text-2);
    }

    .song:hover {
        border-color: var(--border);
    }

    .song.selected {
        background: var(--gold);
        color: #111;
    }

    .loading {
        font-size: 0.75rem;
        color: var(--text-3);
    }

    .error {
        padding: 0.5rem;
        background: rgba(220, 60, 60, 0.1);
        border-radius: 6px;
        color: #e55;
        font-size: 0.85rem;
    }

    /* Results Layout */
    .results-layout {
        flex: 1;
        display: grid;
        grid-template-columns: 280px 1fr;
        gap: 0;
    }

    .sidebar {
        background: var(--surface);
        border-right: 1px solid var(--border);
        padding: 1.25rem;
        display: flex;
        flex-direction: column;
        gap: 1rem;
        height: calc(100vh - 53px);
        overflow-y: auto;
        position: sticky;
        top: 53px;
    }

    .sidebar h3 {
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--text);
    }

    .sidebar h4 {
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--text-3);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }

    .sidebar-section {
        border-top: 1px solid var(--border);
        padding-top: 1rem;
    }

    .sidebar-artist {
        margin-bottom: 0.5rem;
    }

    .sidebar-artist-btn {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 0.6rem;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: 0.85rem;
        color: var(--text);
        text-align: left;
    }

    .sidebar-artist-btn span:first-child {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .sidebar-artist-btn .count {
        background: var(--gold);
        color: #111;
        font-size: 0.65rem;
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-weight: 600;
    }

    .sidebar-artist-btn .arrow {
        color: var(--text-3);
        font-size: 0.7rem;
    }

    .sidebar-artist-btn:hover,
    .sidebar-artist-btn.expanded {
        border-color: var(--gold);
    }

    .sidebar-songs {
        margin-top: 0.4rem;
        max-height: 180px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        padding-left: 0.5rem;
    }

    .s-song {
        padding: 0.35rem 0.5rem;
        background: var(--bg);
        border: 1px solid transparent;
        border-radius: 4px;
        font-size: 0.75rem;
        color: var(--text-2);
        text-align: left;
    }

    .s-song:hover {
        border-color: var(--border);
    }

    .s-song.selected {
        background: var(--gold);
        color: #111;
        border-color: var(--gold);
    }

    .results {
        padding: 1.5rem;
    }

    .results h2 {
        font-size: 1rem;
        font-weight: 500;
        color: var(--text-2);
        margin-bottom: 1.25rem;
    }

    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1rem;
    }

    @media (max-width: 800px) {
        .results-layout {
            grid-template-columns: 1fr;
        }

        .sidebar {
            position: relative;
            top: 0;
            height: auto;
            border-right: none;
            border-bottom: 1px solid var(--border);
        }

        .search-box {
            flex-direction: column;
        }
    }

    @media (max-width: 480px) {
        .landing {
            padding: 1rem;
        }

        .hero h1 {
            font-size: 1.5rem;
        }

        .grid {
            grid-template-columns: 1fr;
        }
    }
</style>
