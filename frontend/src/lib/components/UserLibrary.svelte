<script lang="ts">
    import {
        knownArtists,
        favoriteTracks,
        sidebarPlaying,
        type FavoriteTrack,
    } from "$lib/stores";
    import { trackRemoveKnown, trackRemoveFavorite } from "$lib/analytics";
    import { generateFavouritesHTML } from "$lib/utils/htmlExport";

    interface Props {
        onplay: (track: FavoriteTrack) => void;
        onclose?: () => void;
        showCloseButton?: boolean;
    }

    let { onplay, onclose, showCloseButton = false }: Props = $props();

    // Track collapsed artist groups
    let allCollapsed = $state(false);
    let exportDropdownOpen = $state(false);
    let exportDropdownRef = $state<HTMLDivElement | null>(null);

    // Persist collapsed artists to localStorage
    const COLLAPSED_STORAGE_KEY = 'vibe-collapsed-artists';
    let collapsedArtists = $state<Set<string>>(new Set(
        typeof localStorage !== 'undefined'
            ? JSON.parse(localStorage.getItem(COLLAPSED_STORAGE_KEY) || '[]')
            : []
    ));

    // Save to localStorage whenever collapsedArtists changes
    $effect(() => {
        if (typeof localStorage !== 'undefined') {
            localStorage.setItem(COLLAPSED_STORAGE_KEY, JSON.stringify([...collapsedArtists]));
        }
    });

    // Close dropdown when clicking outside
    function handleExportClickOutside(event: MouseEvent) {
        if (exportDropdownRef && !exportDropdownRef.contains(event.target as Node)) {
            exportDropdownOpen = false;
        }
    }

    const favouritesByArtist = $derived.by(() => {
        const map: Record<string, FavoriteTrack[]> = {};
        for (const fav of $favoriteTracks) {
            const artist = fav.artist_name || "Unknown Artist";
            if (!map[artist]) map[artist] = [];
            map[artist].push(fav);
        }
        return map;
    });

    function toggleArtistCollapse(artist: string) {
        const next = new Set(collapsedArtists);
        if (next.has(artist)) {
            next.delete(artist);
        } else {
            next.add(artist);
        }
        collapsedArtists = next;
        updateAllCollapsedState();
    }

    function toggleAllCollapsed() {
        const artists = Object.keys(favouritesByArtist);
        if (allCollapsed) {
            // Expand all
            collapsedArtists = new Set();
        } else {
            // Collapse all
            collapsedArtists = new Set(artists);
        }
        allCollapsed = !allCollapsed;
    }

    function updateAllCollapsedState() {
        const artists = Object.keys(favouritesByArtist);
        allCollapsed = artists.length > 0 && artists.every(a => collapsedArtists.has(a));
    }

    function removeFromKnown(artist: string) {
        trackRemoveKnown(artist);
        knownArtists.update((list) => list.filter((a) => a !== artist));
    }

    function removeFavorite(track: FavoriteTrack) {
        trackRemoveFavorite(track.track_id, track.track_name, track.artist_name);
        favoriteTracks.update((list) => list.filter((t) => t.track_id !== track.track_id));
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

    function downloadFavouritesJSON() {
        const data = $favoriteTracks.map((t) => ({
            track_id: t.track_id,
            track_name: t.track_name,
            artist_name: t.artist_name,
        }));
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "vibe-favourites.json";
        a.click();
        URL.revokeObjectURL(url);
    }

    function downloadFavouritesHTML() {
        const html = generateFavouritesHTML({
            favourites: favouritesByArtist,
        });
        const blob = new Blob([html], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "vibe-favourites.html";
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
        <h4>Favourites <span class="cnt">{$favoriteTracks.length}</span></h4>
        <div class="header-btns">
            {#if $favoriteTracks.length > 0}
                <button class="header-btn" onclick={toggleAllCollapsed} title={allCollapsed ? "Expand all" : "Collapse all"}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        {#if allCollapsed}
                            <path d="m5 15 7-7 7 7"/>
                        {:else}
                            <path d="m19 9-7 7-7-7"/>
                        {/if}
                    </svg>
                </button>
                <button class="header-btn danger" onclick={clearFavorites} title="Clear all">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                </button>
                <div class="export-dropdown" bind:this={exportDropdownRef}>
                    <button class="header-btn" onclick={() => exportDropdownOpen = !exportDropdownOpen} title="Export">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                    </button>
                    {#if exportDropdownOpen}
                        <!-- svelte-ignore a11y_click_events_have_key_events -->
                        <!-- svelte-ignore a11y_no_static_element_interactions -->
                        <div class="export-menu" onclick={handleExportClickOutside}>
                            <button class="export-option" onclick={() => { downloadFavouritesJSON(); exportDropdownOpen = false; }}>
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
                                </svg>
                                JSON
                            </button>
                            <button class="export-option" onclick={() => { downloadFavouritesHTML(); exportDropdownOpen = false; }}>
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                                </svg>
                                HTML
                            </button>
                        </div>
                    {/if}
                </div>
            {/if}
        </div>
    </div>

    <div class="favourites-list">
        {#if $favoriteTracks.length === 0}
            <span class="empty">No favourite tracks yet</span>
        {/if}
        {#each Object.entries(favouritesByArtist) as [artist, tracks] (artist)}
            <div class="fav-group">
                <button
                    class="fav-artist"
                    class:collapsed={collapsedArtists.has(artist)}
                    onclick={() => toggleArtistCollapse(artist)}
                    tabindex="0"
                    onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleArtistCollapse(artist); } }}
                >
                    <svg class="collapse-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="m6 9 6 6 6-6"/>
                    </svg>
                    {artist}
                    {#if collapsedArtists.has(artist)}
                        <span class="track-count">{tracks.length}</span>
                    {/if}
                </button>
                <div class="fav-tracks-container" class:collapsed={collapsedArtists.has(artist)}>
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
                            <button class="remove-btn" onclick={(e) => { e.stopPropagation(); removeFavorite(track); }}>×</button>
                        </div>
                    {/each}
                </div>
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

    .favourites-list {
        flex: 1;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
        padding-right: 0.25rem;
    }

    .favourites-list::-webkit-scrollbar { width: 6px; }
    .favourites-list::-webkit-scrollbar-track { background: transparent; }
    .favourites-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    .favourites-list::-webkit-scrollbar-thumb:hover { background: var(--text-3); }

    .export-dropdown {
        position: relative;
    }

    .export-menu {
        position: absolute;
        top: calc(100% + 4px);
        right: 0;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 4px;
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 100px;
        z-index: 10;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }

    .export-option {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        background: transparent;
        border: none;
        border-radius: 4px;
        color: var(--text-2);
        font-size: 0.75rem;
        cursor: pointer;
        text-align: left;
    }

    .export-option:hover {
        background: var(--bg-alt);
        color: var(--text);
    }

    .fav-group {
        display: flex;
        flex-direction: column;
    }

    .fav-artist {
        display: flex;
        align-items: center;
        gap: 0.3rem;
        font-size: 0.7rem;
        font-weight: 600;
        color: var(--gold);
        background: none;
        border: none;
        padding: 0.15rem 0;
        cursor: pointer;
        text-align: left;
        transition: opacity 0.15s;
    }

    .fav-artist:hover {
        opacity: 0.8;
    }

    .fav-artist:focus-visible {
        outline: none;
        border-radius: 4px;
        box-shadow: 0 0 0 2px var(--gold-glow);
    }

    .collapse-icon {
        transition: transform 0.2s ease;
        flex-shrink: 0;
    }

    .fav-artist.collapsed .collapse-icon {
        transform: rotate(-90deg);
    }

    .track-count {
        font-size: 0.65rem;
        color: var(--text-3);
        font-weight: 500;
        margin-left: 0.2rem;
    }

    .fav-tracks-container {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
        overflow: hidden;
        transition: max-height 0.2s ease, opacity 0.2s ease, margin 0.2s ease;
        max-height: 1000px;
        opacity: 1;
        margin-top: 0.1rem;
    }

    .fav-tracks-container.collapsed {
        max-height: 0;
        opacity: 0;
        margin-top: 0;
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
