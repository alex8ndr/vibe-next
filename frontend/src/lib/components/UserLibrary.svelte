<script lang="ts">
    import {
        knownArtists,
        favoriteTracks,
        sidebarPlaying,
        type FavoriteTrack,
        type Track,
    } from "$lib/stores";

    interface Props {
        onplay: (track: FavoriteTrack) => void;
        onclose?: () => void;
        showCloseButton?: boolean;
    }

    let { onplay, onclose, showCloseButton = false }: Props = $props();

    const favoritesByArtist = $derived.by(() => {
        const map: Record<string, FavoriteTrack[]> = {};
        for (const fav of $favoriteTracks) {
            const artist = fav.artist_name || "Unknown Artist";
            if (!map[artist]) map[artist] = [];
            map[artist].push(fav);
        }
        return map;
    });

    function removeFromKnown(artist: string) {
        knownArtists.update((list) => list.filter((a) => a !== artist));
    }

    function removeFavorite(trackId: string) {
        favoriteTracks.update((list) =>
            list.filter((t) => t.track_id !== trackId),
        );
    }

    function downloadFavoritesJSON() {
        const data = $favoriteTracks.map((t) => ({
            track_id: t.track_id,
            track_name: t.track_name,
            artist_name: t.artist_name,
        }));
        const blob = new Blob([JSON.stringify(data, null, 2)], {
            type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "vibe-favorites.json";
        a.click();
        URL.revokeObjectURL(url);
    }
</script>

<div class="user-library">
    <div class="favorites-section">
        <div class="favorites-header">
            <h4>Known Artists <span class="cnt">{$knownArtists.length}</span></h4>
            {#if showCloseButton && onclose}
                <button
                    class="icon-btn close-btn"
                    onclick={onclose}
                    aria-label="Close sidebar"
                >
                    <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                </button>
            {/if}
        </div>
        <p class="side-hint">Won't be recommended</p>

        <div class="known-chips">
            {#if $knownArtists.length === 0}
                <span class="side-empty">No artists marked as known</span>
            {/if}
            {#each $knownArtists as artist (artist)}
                <button class="known-chip" onclick={() => removeFromKnown(artist)}>
                    {artist} <span class="x">×</span>
                </button>
            {/each}
        </div>

        <div class="favorites-header mt-lg">
            <h4>Favorites <span class="cnt">{$favoriteTracks.length}</span></h4>
            {#if $favoriteTracks.length > 0}
                <button
                    class="fav-download-btn"
                    onclick={downloadFavoritesJSON}
                    title="Export favorites"
                    aria-label="Export favorites"
                >
                    <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                </button>
            {/if}
        </div>

        <div class="favorites-grouped">
            {#if $favoriteTracks.length === 0}
                <span class="side-empty">No favorite tracks yet</span>
            {/if}
            {#each Object.entries(favoritesByArtist) as [artist, tracks] (artist)}
                <div class="fav-group">
                    <span class="fav-artist-name">{artist}</span>
                    {#each tracks as track (track.track_id)}
                        <div
                            class="fav-track-row"
                            class:playing={$sidebarPlaying?.trackId === track.track_id}
                            role="button"
                            tabindex="0"
                            onclick={() => onplay(track)}
                            onkeydown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    onplay(track);
                                }
                            }}
                        >
                            <span class="fav-track-name">{track.track_name}</span>
                            <button
                                class="fav-remove"
                                onclick={(e) => {
                                    e.stopPropagation();
                                    removeFavorite(track.track_id);
                                }}>×</button
                            >
                        </div>
                    {/each}
                </div>
            {/each}
        </div>
    </div>
</div>

<style>
    .user-library {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-height: 0;
    }

    .favorites-section {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-height: 0;
    }

    .cnt {
        color: var(--gold);
        font-weight: 500;
        margin-left: 0.3rem;
        font-size: 0.8em;
    }

    .close-btn {
        margin-left: auto;
    }

    /* Styles moved from page.css */
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

    .favorites-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
        margin-bottom: 0.75rem;
    }

    .favorites-header h4 {
        margin: 0;
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--text);
    }

    .fav-download-btn {
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 4px;
        font-size: 0.7rem;
        color: var(--text-2);
        cursor: pointer;
    }

    .fav-download-btn:hover {
        border-color: var(--gold);
        color: var(--text);
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
    
    .side-empty {
        font-size: 0.75rem;
        color: var(--text-3);
        font-style: italic;
    }

    .side-hint {
        font-size: 0.65rem;
        color: var(--text-3);
        margin-bottom: 0.5rem;
        margin-top: -0.5rem;
    }

    /* Helper utility */
    .mt-lg {
        margin-top: 1.5rem;
    }
</style>
