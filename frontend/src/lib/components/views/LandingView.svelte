<script lang="ts">
    import ArtistSelect from "$lib/components/ArtistSelect.svelte";
    import UserLibrary from "$lib/components/UserLibrary.svelte";
    import VibeControls from "$lib/components/VibeControls.svelte";
    import { fetchArtistTracks } from "$lib/api";
    import {
        LANDING_VISIBLE_EXAMPLES,
        LANDING_EXAMPLE_DEFAULTS,
        type LandingExample,
        type LandingExampleSearchRequest,
    } from "$lib/landingExamples";
    import {
        settings,
        isLoading,
        loadingProgress,
        progressPhase,
        knownArtists,
        favoriteTracks,
        sidebarPlaying,
        LIMITS,
        DEFAULT_SETTINGS,
        type Track,
        type FavoriteTrack,
    } from "$lib/stores";
    import bgDark from "$lib/assets/background_dark.webp";
    import bgLight from "$lib/assets/background_light.webp";

    let {
        selected = $bindable(),
        fineTune = $bindable(),
        artistTracks,
        error,
        datasetStats = null,
        onsearch, // event prop
        onplay,   // event prop for playing tracks
    } = $props<{
        selected: string[];
        fineTune: Record<string, string[]>;
        artistTracks: Record<string, Track[]>;
        error: string | null;
        datasetStats?: { track_count: number; artist_count: number } | null;
        onsearch: (request?: LandingExampleSearchRequest) => void | Promise<void>;
        onplay: (track: FavoriteTrack) => void;
    }>();

    function formatStat(n: number): string {
        if (n >= 1_000_000) return `${Math.floor(n / 100_0000)}M+`;
        if (n >= 1_000) return `${Math.floor(n / 1_0000) * 10}K+`;
        return `${n}`;
    }

    // Local state
    let showLandingPanel = $state(false);
    let showVibePanel = $state(false);
    let heroExpandedArtist = $state<string | null>(null);
    let songSearch = $state("");
    let exampleTracks = $state<Record<string, Track[]>>({});
    let previousSelectedKey = $state("");
    let exampleSearchInFlight = $state(false);

    // Derived
    const atMaxArtists = $derived(selected.length >= LIMITS.MAX_INPUT_ARTISTS);
    const isReturningUser = $derived(
        $knownArtists.length > 0 || $favoriteTracks.length > 0
    );

    $effect(() => {
        const nextSelectedKey = selected.join("\u0000");
        const selectionChanged = nextSelectedKey !== previousSelectedKey;
        const hadSelection = previousSelectedKey.length > 0;

        if (!selectionChanged) {
            return;
        }

        previousSelectedKey = nextSelectedKey;

        if (selected.length === 0) {
            heroExpandedArtist = null;
            songSearch = "";
            return;
        }

        if (!hadSelection || !heroExpandedArtist || !selected.includes(heroExpandedArtist)) {
            heroExpandedArtist = selected[0];
            songSearch = "";
        }
    });

    // Actions
    function toggleHeroExpanded(artist: string) {
        if (heroExpandedArtist === artist) {
            heroExpandedArtist = null;
        } else {
            heroExpandedArtist = artist;
            songSearch = "";
        }
    }

    function toggleSong(artist: string, song: string) {
        const cur = fineTune[artist] || [];
        if (cur.includes(song)) {
            fineTune = { ...fineTune, [artist]: cur.filter((s: string) => s !== song) };
        } else if (cur.length < LIMITS.MAX_INPUT_SONGS_PER_ARTIST) {
            fineTune = { ...fineTune, [artist]: [...cur, song] };
        }
    }

    function isAtSongLimit(artist: string): boolean {
        return (
            (fineTune[artist]?.length || 0) >= LIMITS.MAX_INPUT_SONGS_PER_ARTIST
        );
    }

    function normalizeTrackName(name: string): string {
        return name.trim().toLowerCase().replace(/\s+/g, " ");
    }

    async function getExampleTracks(artist: string): Promise<Track[]> {
        if (exampleTracks[artist]) {
            return exampleTracks[artist];
        }

        const tracks = await fetchArtistTracks(artist);
        exampleTracks = { ...exampleTracks, [artist]: tracks };
        return tracks;
    }

    async function resolveExampleFineTune(
        example: LandingExample,
    ): Promise<Record<string, string[]>> {
        if (!example.songs) {
            return {};
        }

        const fineTuneFromSongs: Record<string, string[]> = {};

        for (const [artist, songNames] of Object.entries(example.songs)) {
            if (!songNames.length) {
                continue;
            }

            try {
                const tracks = await getExampleTracks(artist);
                const byName = new Map(
                    tracks.map((track) => [normalizeTrackName(track.track_name), track.track_id]),
                );
                const resolvedTrackIds = songNames
                    .map((songName) => byName.get(normalizeTrackName(songName)))
                    .filter((trackId): trackId is string => Boolean(trackId));

                if (resolvedTrackIds.length) {
                    fineTuneFromSongs[artist] = resolvedTrackIds;
                }
            } catch {
                // Ignore missing preset songs for landing examples and fall back to artist-only seeds.
            }
        }

        return fineTuneFromSongs;
    }

    function getExampleSongCount(example: LandingExample): number {
        return Object.values(example.songs || {}).reduce(
            (total, songs) => total + songs.length,
            0,
        );
    }

    async function applyExampleAndSearch(example: LandingExample) {
        if (exampleSearchInFlight) return;
        exampleSearchInFlight = true;
        try {
            const exampleSearchRequest: LandingExampleSearchRequest = {
                artists: [...example.artists],
                fineTune: await resolveExampleFineTune(example),
                settings: {
                    ...LANDING_EXAMPLE_DEFAULTS,
                    ...example.settings,
                },
            };

            await onsearch(exampleSearchRequest);
        } finally {
            exampleSearchInFlight = false;
        }
    }
</script>

<svelte:head>
    <link rel="preload" as="image" href={bgDark} />
    <link rel="preload" as="image" href={bgLight} />
</svelte:head>

<div class="landing">
    {#if $settings.showBackground}
        <div class="bg-image"></div>
        <div class="bg-fade"></div>
    {/if}

    <div class="hero">
        <div class="hero-content">
            <div class="hero-primary">
                <h1>Discover your next<br />favourite artist</h1>
                <p class="tagline">
                    Personalized music recommendations based on your unique taste
                </p>

                <div class="search-row">
                    <ArtistSelect
                        bind:selected
                        max={LIMITS.MAX_INPUT_ARTISTS}
                        placeholder="Search artists..."
                    />
                    <button
                        class="btn-go"
                        data-phase={$progressPhase}
                        style:--progress={$loadingProgress / 100}
                        onclick={() => onsearch()}
                        disabled={!selected.length || $isLoading}
                    >
                        <span class="btn-label">Discover</span>
                    </button>
                </div>

                {#if atMaxArtists}
                    <p class="limit-msg">
                        Maximum {LIMITS.MAX_INPUT_ARTISTS} artists reached
                    </p>
                {/if}
            </div>

            <div class="fine-section" class:selected={selected.length > 0}>
            {#if selected.length === 0}
                <div class="example-heading">
                    <span class="fine-label">Click to try an example:</span>
                </div>

                <div class="example-list">
                    <div class="example-grid">
                        {#each LANDING_VISIBLE_EXAMPLES as example (example.id)}
                            <button
                                class="example-card"
                                class:wide={example.wide}
                                onclick={() => applyExampleAndSearch(example)}
                                title={`Search ${example.artists.join(", ")}`}
                                disabled={$isLoading || exampleSearchInFlight}
                            >
                                <div class="example-card-top">
                                    <span class="example-count">
                                        {example.artists.length} {example.artists.length ===
                                        1
                                            ? "artist"
                                            : "artists"}
                                        {#if getExampleSongCount(example) > 0}
                                            {@const songCount = getExampleSongCount(example)}
                                            <span class="example-song-badge"
                                                >+{songCount} {songCount === 1 ? "song" : "songs"}</span
                                            >
                                        {/if}
                                    </span>
                                    <span class="example-lane">{example.lane}</span>
                                </div>
                                <div class="example-artists">
                                    {#if example.wide}
                                        <span class="example-artist-line">{example.artists.join(", ")}</span>
                                    {:else}
                                        {#each example.artists as artist (artist)}
                                            {@const songs = example.songs?.[artist] || []}
                                            <span class="example-artist-line">{artist}</span>
                                            {#if songs.length}
                                                <span class="example-song-line">{songs.join(", ")}</span>
                                            {/if}
                                        {/each}
                                    {/if}
                                </div>
                            </button>
                        {/each}
                    </div>
                </div>
            {:else}
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
                            <input
                                type="text"
                                class="landing-song-search"
                                placeholder="Search..."
                                bind:value={songSearch}
                                onclick={(e) => e.stopPropagation()}
                            />
                        </div>
                        <div class="songs-scroll">
                            {#each (artistTracks[heroExpandedArtist] || []).filter((t: Track) => !songSearch || t.track_name.toLowerCase().includes(songSearch.toLowerCase())) as t (t.track_id)}
                                {@const sel = (
                                    fineTune[heroExpandedArtist] || []
                                ).includes(t.track_id)}
                                {@const atLimit =
                                    isAtSongLimit(heroExpandedArtist)}
                                <button
                                    class="song-chip"
                                    class:on={sel}
                                    class:disabled={!sel && atLimit}
                                    onclick={() =>
                                        toggleSong(
                                            heroExpandedArtist!,
                                            t.track_id,
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
                        {#if (fineTune[heroExpandedArtist]?.length || 0) >= LIMITS.MAX_INPUT_SONGS_PER_ARTIST}
                            <div class="limit-indicator">
                                {fineTune[heroExpandedArtist].length}/{LIMITS.MAX_INPUT_SONGS_PER_ARTIST}
                                songs selected
                            </div>
                        {/if}
                    </div>
                {/if}
            {/if}
            </div>
        </div>

        {#if error}
            <p class="error">{error}</p>
        {/if}

        {#if datasetStats}
            <div class="dataset-stats dataset-stats-mobile">
                <span>🎵 {formatStat(datasetStats.track_count)} songs</span>
                <span class="stats-sep">·</span>
                <span>🎤 {formatStat(datasetStats.artist_count)} artists</span>
            </div>
        {/if}

        {#if isReturningUser}
            <button
                class="landing-vibe-toggle"
                onclick={() => (showVibePanel = !showVibePanel)}
            >
                {showVibePanel ? "✕" : "⚙"}
            </button>
            <button
                class="landing-lists-toggle"
                onclick={() => (showLandingPanel = !showLandingPanel)}
            >
                {showLandingPanel ? "✕" : `♥ ${$favoriteTracks.length}`}
            </button>
        {/if}

        {#if showLandingPanel}
            <aside class="landing-lists-panel">
                <UserLibrary {onplay} />
            </aside>
        {/if}

        <!-- Hidden sidebar player for landing page favorites playback -->
        {#if $sidebarPlaying}
            <div class="landing-player-wrap">
                <div class="landing-player-info">
                    <span class="landing-player-track">{$sidebarPlaying.trackName}</span>
                    <span class="landing-player-artist">{$sidebarPlaying.artist}</span>
                </div>
            </div>
        {/if}

        {#if showVibePanel}
            <aside class="landing-vibe-panel">
                <div class="vibe-header">
                    <h4>Customize Your Vibe</h4>
                    <button class="icon-btn custom-reset-btn" onclick={() => settings.set(DEFAULT_SETTINGS)} title="Reset to defaults">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg
                        >
                    </button>
                </div>

                <VibeControls />
            </aside>
        {/if}

    </div>

    {#if datasetStats}
        <div class="dataset-stats dataset-stats-desktop">
            <span>🎵 {formatStat(datasetStats.track_count)} songs</span>
            <span class="stats-sep">·</span>
            <span>🎤 {formatStat(datasetStats.artist_count)} artists</span>
        </div>
    {/if}
</div>

<style>
    .dataset-stats {
        font-size: 0.75rem;
        color: var(--text-3);
        text-align: center;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        opacity: 0.7;
    }

    .dataset-stats-desktop {
        position: absolute;
        bottom: 1.5rem;
        left: 0;
        right: 0;
    }

    .dataset-stats-mobile {
        display: none;
        margin-top: auto;
        padding-top: 1rem;
    }

    .stats-sep {
        opacity: 0.5;
    }

    @media (max-width: 768px) {
        .dataset-stats-desktop {
            display: none;
        }

        .dataset-stats-mobile {
            display: flex;
        }
    }
</style>
