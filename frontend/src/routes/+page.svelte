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
        settings,
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
                diversity: $settings.variety,
                max_artists: $settings.maxResults,
                genre_weight: $settings.genreWeight,
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
    <!-- Landing -->
    <div class="landing">
        {#if $settings.showBackground}
            <div class="bg-image"></div>
            <div class="bg-fade"></div>
        {/if}

        <div class="hero">
            <h1>Discover your next<br />favorite artist</h1>
            <p class="tagline">
                Music recommendations based on what you already love
            </p>

            <div class="search-row">
                <ArtistSelect
                    {selected}
                    onchange={(a) => (selected = a)}
                    max={5}
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

            {#if selected.length > 0}
                <div class="fine-section">
                    <div class="fine-row">
                        <span class="fine-label">Fine-tune:</span>
                        {#each selected as artist (artist)}
                            <button
                                class="fine-btn"
                                class:open={expandedArtist === artist}
                                onclick={() =>
                                    (expandedArtist =
                                        expandedArtist === artist
                                            ? null
                                            : artist)}
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

                    {#if expandedArtist}
                        <div class="songs-box">
                            <div class="songs-scroll">
                                {#each artistTracks[expandedArtist] || [] as t (t.track_id)}
                                    {@const sel = (
                                        fineTune[expandedArtist] || []
                                    ).includes(t.track_name)}
                                    <button
                                        class="song-chip"
                                        class:on={sel}
                                        onclick={() =>
                                            toggleSong(
                                                expandedArtist!,
                                                t.track_name,
                                            )}
                                    >
                                        {t.track_name.length > 35
                                            ? t.track_name.slice(0, 35) + "…"
                                            : t.track_name}
                                    </button>
                                {/each}
                                {#if !artistTracks[expandedArtist]}
                                    <span class="muted">Loading...</span>
                                {/if}
                            </div>
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
    <div class="results-wrap">
        <aside class="side">
            <h3>Search</h3>
            <div class="side-search">
                <ArtistSelect
                    {selected}
                    onchange={(a) => (selected = a)}
                    max={5}
                    placeholder="Add artists..."
                />
            </div>
            <button
                class="btn-update"
                onclick={search}
                disabled={!selected.length || $isLoading}
            >
                {$isLoading ? "Updating..." : "Update"}
            </button>

            {#if selected.length > 0}
                <div class="side-section">
                    <h4>Fine-tune</h4>
                    {#each selected as artist (artist)}
                        <div class="side-artist">
                            <button
                                class="side-artist-btn"
                                class:open={expandedArtist === artist}
                                onclick={() =>
                                    (expandedArtist =
                                        expandedArtist === artist
                                            ? null
                                            : artist)}
                            >
                                <span class="name">{artist}</span>
                                {#if (fineTune[artist]?.length || 0) > 0}
                                    <span class="cnt"
                                        >{fineTune[artist].length}</span
                                    >
                                {/if}
                                <span class="arr"
                                    >{expandedArtist === artist
                                        ? "▾"
                                        : "▸"}</span
                                >
                            </button>

                            {#if expandedArtist === artist}
                                <div class="side-songs">
                                    {#each artistTracks[artist] || [] as t (t.track_id)}
                                        {@const sel = (
                                            fineTune[artist] || []
                                        ).includes(t.track_name)}
                                        <button
                                            class="ss"
                                            class:on={sel}
                                            onclick={() =>
                                                toggleSong(
                                                    artist,
                                                    t.track_name,
                                                )}
                                        >
                                            {t.track_name.length > 26
                                                ? t.track_name.slice(0, 26) +
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

        <section class="main-results">
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

    .song-chip:hover {
        border-color: var(--border);
    }

    .song-chip.on {
        background: var(--gold);
        color: #111;
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
    }

    .side {
        background: var(--surface);
        border-right: 1px solid var(--border);
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        height: calc(100vh - 52px);
        overflow-y: auto;
        position: sticky;
        top: 52px;
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
        max-height: 160px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
        padding-left: 0.4rem;
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

    .ss:hover {
        border-color: var(--border);
    }

    .ss.on {
        background: var(--gold);
        color: #111;
        border-color: var(--gold);
    }

    .main-results {
        padding: 1.25rem;
    }

    .main-results h2 {
        font-size: 0.95rem;
        font-weight: 500;
        color: var(--text-2);
        margin-bottom: 1rem;
    }

    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
        gap: 1rem;
    }

    @media (max-width: 768px) {
        .results-wrap {
            grid-template-columns: 1fr;
        }

        .side {
            position: relative;
            top: 0;
            height: auto;
            border-right: none;
            border-bottom: 1px solid var(--border);
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
    }
</style>
