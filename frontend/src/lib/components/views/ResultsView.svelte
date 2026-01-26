<script lang="ts">
    import ArtistSelect from "$lib/components/ArtistSelect.svelte";
    import ArtistCard from "$lib/components/ArtistCard.svelte";
    import UserLibrary from "$lib/components/UserLibrary.svelte";
    import VibeControls from "$lib/components/VibeControls.svelte";
    import {
        artistsList,
        recommendations,
        isLoading,
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
    
    // Actions
    function toggleExpanded(artist: string) {
        const next = new Set(expandedArtists);
        if (next.has(artist)) {
            next.delete(artist);
        } else {
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
            if (list.includes(artist)) return list;
            return [...list, artist];
        });
    }

    function addToSearch(artist: string) {
         if (
            !selected.includes(artist) &&
            selected.length < LIMITS.MAX_INPUT_ARTISTS
        ) {
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

<div class="results-wrap" class:right-open={$rightPanelOpen}>
    <aside class="side left">
        <h3>Search</h3>
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
            </div>
        </div>

        <div class="grid">
            {#each Object.entries($recommendations) as [artist, tracks] (artist + '-' + (tracks[0]?.track_id || ''))}
                <ArtistCard 
                    {artist} 
                    {tracks}
                    isKnown={$knownArtists.includes(artist)}
                    onAddToKnown={() => addToKnown(artist)}
                    onAddToSearch={() => addToSearch(artist)}
                    onAddFavorite={createAddFavoriteHandler(artist)}
                />
            {/each}
        </div>
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
</div>
