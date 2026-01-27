<script lang="ts">
    import ArtistSelect from "$lib/components/ArtistSelect.svelte";
    import ArtistCard from "$lib/components/ArtistCard.svelte";
    import UserLibrary from "$lib/components/UserLibrary.svelte";
    import VibeControls from "$lib/components/VibeControls.svelte";
    import { generateHTML } from "$lib/utils/htmlExport";
    import {
        recommendations,
        isLoading,
        settings,
        knownArtists,
        favoriteTracks,
        rightPanelOpen,
        sidebarPlaying,
        mobileSidebarOpen,
        LIMITS,
        type Track,
        type FavoriteTrack,
    } from "$lib/stores";

    let {
        selected = $bindable(),
        fineTune = $bindable(),
        artistTracks,
        onsearch,
        onplay, // event prop
    } = $props<{
        selected: string[];
        fineTune: Record<string, string[]>;
        artistTracks: Record<string, Track[]>;
        onsearch: () => void;
        onplay: (track: FavoriteTrack) => void;
    }>();

    // Local state
    let expandedArtists = $state<Set<string>>(new Set());
    let globalSongSearch = $state("");

    // Derived
    const atMaxArtists = $derived(selected.length >= LIMITS.MAX_INPUT_ARTISTS);
    const hasRecommendations = $derived(Object.keys($recommendations).length > 0);
    
    const SINGLE_EXPAND = true;

    // Actions
    function toggleExpanded(artist: string) {
        const next = new Set(expandedArtists);
        if (next.has(artist)) {
            next.delete(artist);
        } else {
            if (SINGLE_EXPAND) next.clear();
            next.add(artist);
        }
        expandedArtists = next;
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

    function getFilteredTracks(
        artist: string,
        searchQuery: string = "",
    ): Track[] {
        const tracks = artistTracks[artist] || [];
        const query = searchQuery.toLowerCase();
        if (!query) return tracks;
        return tracks.filter((t: Track) => t.track_name.toLowerCase().includes(query));
    }

    function resetSettings() {
        settings.set({
            variety: 2,
            genreWeight: 2.0,
            maxResults: LIMITS.MAX_RESULT_ARTISTS.default,
            tracksPerArtist: LIMITS.MAX_TRACKS_PER_ARTIST.default,
            showBackground: true,
            vibeMood: 0,
            vibeSound: 0,
            popularity: 0,
        });
    }

    function addToKnown(artist: string) {
        knownArtists.update((list) => {
            if (list.includes(artist)) {
                return list.filter(a => a !== artist);
            }
            return [...list, artist];
        });
    }

    function addToSearch(artist: string) {
        if (selected.includes(artist)) {
            selected = selected.filter((a: string) => a !== artist);
        } else if (selected.length < LIMITS.MAX_INPUT_ARTISTS) {
            selected = [...selected, artist];
        }
    }

    // Helper to add favorite with artist context within the loop
    function createAddFavoriteHandler(artist: string) {
        return (track: Track) => {
             favoriteTracks.update((list) => {
                if (list.some((t) => t.track_id === track.track_id)) return list;
                return [...list, { ...track, artist_name: artist }];
            });
        };
    }

    function downloadHTML() {
        const html = generateHTML({
            recommendations: $recommendations,
            selectedArtists: selected,
        });
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

<div class="results-wrap" class:right-open={$rightPanelOpen}>
    <aside class="side left">
        <div class="side-search">
            <ArtistSelect
                bind:selected
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
            onclick={onsearch}
            disabled={!selected.length || $isLoading}
        >
            {$isLoading ? "Updating..." : "Update"}
        </button>

        {#if selected.length > 0}
            <div class="side-section fine-tune-section">
                <div class="fine-header">
                    <h4>Fine-tune</h4>
                    <div class="search-input-wrap">
                        <input
                            type="text"
                            class="side-song-search"
                            placeholder="Search songs..."
                            bind:value={globalSongSearch}
                        />
                        {#if globalSongSearch}
                            <button 
                                class="clear-btn" 
                                onclick={() => globalSongSearch = ""}
                                aria-label="Clear search"
                            >
                                ×
                            </button>
                        {/if}
                    </div>
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
                                        <span class="muted">No matches</span>
                                    {/if}
                                </div>

                            {/if}
                        </div>
                    {/each}
                </div>
            </div>
        {/if}

        {#if selected.length === 0}
            <div class="spacer"></div>
        {/if}

        <div class="side-section customize-section">
            <div class="customize-header">
                <h4>Customize Your Vibe</h4>
                <button class="reset-btn" onclick={resetSettings} title="Reset to defaults" aria-label="Reset to defaults">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>
                    </svg>
                </button>
            </div>

            <VibeControls />
        </div>
    </aside>

    <section class="main-results">
        <div class="results-header">
            <h2>{Object.keys($recommendations).length} artists for you</h2>
            <div class="results-actions">
                <button
                    class="btn-action"
                    onclick={downloadHTML}
                    disabled={!hasRecommendations}
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
                    disabled={!hasRecommendations}
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
            </div>
        </div>

        {#if !hasRecommendations}
            <div class="empty-state">
                <p>No recommendations yet.</p>
                <p class="muted">Add artists and click Update to get started.</p>
            </div>
        {:else}
        <div class="grid">
            {#each Object.entries($recommendations) as [artist, tracks] (artist + '-' + (tracks[0]?.track_id || ''))}
                <ArtistCard 
                    {artist} 
                    {tracks}
                    isKnown={$knownArtists.includes(artist)}
                    isAdded={selected.includes(artist)}
                    onAddToKnown={() => addToKnown(artist)}
                    onAddToSearch={() => addToSearch(artist)}
                    onAddFavorite={createAddFavoriteHandler(artist)}
                />
            {/each}
        </div>
        {/if}
    </section>

    <div class="side-right-toggle" class:hidden={$rightPanelOpen}>
        <button
            class="btn-panel-toggle"
            onclick={() => rightPanelOpen.set(true)}
            aria-label="Open side panel"
        >
            <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
            >
                <path d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
        </button>
    </div>

    <aside class="side right" class:mobile-open={$mobileSidebarOpen}>
        <button class="mobile-close-btn" onclick={() => mobileSidebarOpen.set(false)} aria-label="Close sidebar">
            ✕
        </button>

        <UserLibrary 
            {onplay} 
            showCloseButton={true} 
            onclose={() => rightPanelOpen.set(false)} 
        />

        {#if $sidebarPlaying}
            <div class="player-section">
                <div class="player-info">
                    <span class="player-track">{$sidebarPlaying.trackName}</span>
                    <span class="player-artist"
                        >{$sidebarPlaying.artist}</span
                    >
                </div>
            </div>
        {/if}
    </aside>

    <!-- Mobile library toggle (matches landing page style) -->
    <button
        class="landing-lists-toggle mobile-only"
        onclick={() => mobileSidebarOpen.update(v => !v)}
    >
        ♥ {$favoriteTracks.length}
    </button>
</div>
