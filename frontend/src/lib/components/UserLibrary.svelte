<script lang="ts">
    import {
        knownArtists,
        favoriteTracks,
        sidebarPlaying,
        type FavoriteTrack,
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
        favoriteTracks.update((list) => list.filter((t) => t.track_id !== trackId));
    }

    function clearKnownArtists() {
        if (window.confirm("Clear all known artists?")) {
            knownArtists.set([]);
        }
    }

    function clearFavorites() {
        if (window.confirm("Clear all favorites? This cannot be undone.")) {
            favoriteTracks.set([]);
        }
    }

    function downloadFavoritesJSON() {
        const data = $favoriteTracks.map((t) => ({
            track_id: t.track_id,
            track_name: t.track_name,
            artist_name: t.artist_name,
        }));
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "vibe-favorites.json";
        a.click();
        URL.revokeObjectURL(url);
    }
</script>

<div class="user-library">
    <div class="section-header">
        <h4>Known Artists <span class="cnt">{$knownArtists.length}</span></h4>
        <div class="header-btns">
            {#if $knownArtists.length > 0}
                <button class="header-btn danger" onclick={clearKnownArtists} title="Clear all">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                </button>
            {/if}
            {#if showCloseButton && onclose}
                <button class="header-btn" onclick={onclose} title="Close panel">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                </button>
            {/if}
        </div>
    </div>
    <p class="hint">Won't be recommended</p>

    <div class="known-chips">
        {#if $knownArtists.length === 0}
            <span class="empty">No artists marked as known</span>
        {/if}
        {#each $knownArtists as artist (artist)}
            <button class="chip" onclick={() => removeFromKnown(artist)}>
                {artist} <span class="x">×</span>
            </button>
        {/each}
    </div>

    <div class="section-header mt">
        <h4>Favorites <span class="cnt">{$favoriteTracks.length}</span></h4>
        <div class="header-btns">
            {#if $favoriteTracks.length > 0}
                <button class="header-btn danger" onclick={clearFavorites} title="Clear all">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                </button>
                <button class="header-btn" onclick={downloadFavoritesJSON} title="Export">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                </button>
            {/if}
        </div>
    </div>

    <div class="favorites-list">
        {#if $favoriteTracks.length === 0}
            <span class="empty">No favorite tracks yet</span>
        {/if}
        {#each Object.entries(favoritesByArtist) as [artist, tracks] (artist)}
            <div class="fav-group">
                <span class="fav-artist">{artist}</span>
                {#each tracks as track (track.track_id)}
                    <div
                        class="fav-track"
                        class:playing={$sidebarPlaying?.trackId === track.track_id}
                        role="button"
                        tabindex="0"
                        onclick={() => onplay(track)}
                        onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onplay(track); } }}
                    >
                        <span class="track-name">{track.track_name}</span>
                        <button class="remove-btn" onclick={(e) => { e.stopPropagation(); removeFavorite(track.track_id); }}>×</button>
                    </div>
                {/each}
            </div>
        {/each}
    </div>
</div>

<style>
    .user-library {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-height: 0;
    }

    .section-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
    }

    .section-header h4 {
        margin: 0;
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .header-btns {
        margin-left: auto;
        display: flex;
        gap: 4px;
    }

    .header-btn {
        width: 24px;
        height: 24px;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 4px;
        color: var(--text-2);
        cursor: pointer;
    }

    .header-btn:hover {
        border-color: var(--gold);
        color: var(--text);
    }

    .header-btn.danger:hover {
        border-color: #e55;
        color: #e55;
    }

    .cnt {
        color: var(--gold);
        font-weight: 500;
        margin-left: 0.3rem;
        font-size: 0.8em;
    }

    .hint {
        font-size: 0.65rem;
        color: var(--text-3);
        margin: 0 0 0.5rem 0;
    }

    .mt { margin-top: 1.5rem; }

    .empty {
        font-size: 0.75rem;
        color: var(--text-3);
        font-style: italic;
    }

    .known-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.3rem;
        max-height: 25%;
        overflow-y: auto;
        padding-right: 0.25rem;
    }

    .known-chips::-webkit-scrollbar { width: 6px; }
    .known-chips::-webkit-scrollbar-track { background: transparent; }
    .known-chips::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    .known-chips::-webkit-scrollbar-thumb:hover { background: var(--text-3); }

    .chip {
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

    .chip:hover { border-color: #e55; }
    .chip .x { color: var(--text-3); font-size: 0.8rem; }
    .chip:hover .x { color: #e55; }

    .favorites-list {
        flex: 1;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        padding-right: 0.25rem;
    }

    .favorites-list::-webkit-scrollbar { width: 6px; }
    .favorites-list::-webkit-scrollbar-track { background: transparent; }
    .favorites-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    .favorites-list::-webkit-scrollbar-thumb:hover { background: var(--text-3); }

    .fav-group {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
    }

    .fav-artist {
        font-size: 0.7rem;
        font-weight: 600;
        color: var(--gold);
        margin-bottom: 0.15rem;
    }

    .fav-track {
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

    .fav-track:hover { background: var(--border); }
    .fav-track.playing { background: var(--gold); color: #111; }
    .fav-track.playing .track-name { color: #111; }
    .fav-track.playing .remove-btn { color: #333; }
    .fav-track.playing .remove-btn:hover { color: #900; }

    .track-name {
        font-size: 0.75rem;
        color: var(--text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: 1;
        min-width: 0;
    }

    .remove-btn {
        background: none;
        border: none;
        color: var(--text-3);
        font-size: 0.9rem;
        padding: 0;
        line-height: 1;
        margin-left: 0.5rem;
    }

    .remove-btn:hover { color: #e55; }
</style>
