<script lang="ts">
    import {
        knownArtists,
        favoriteTracks,
        sidebarPlaying,
        sidebarPlayerStatus,
        sidebarLoadingTrackId,
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
    let showExportLabel = $state(true);
    let exportDropdownOpen = $state(false);
    let exportDropdownRef = $state<HTMLDivElement | null>(null);
    let copyStatus = $state<"idle" | "copied" | "failed">("idle");
    let exportTooltipOpen = $state(false);
    let exportTooltipRef = $state<HTMLDivElement | null>(null);

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

    const canPlaySidebar = $derived($sidebarPlayerStatus === "ready");

    async function copyFavouritesText() {
        const text = $favoriteTracks
            .map((track) => `${track.artist_name} - ${track.track_name}`)
            .join("\n");
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            copyStatus = "copied";
        } catch {
            copyStatus = "failed";
        }
        exportTooltipOpen = true;
        if (copyStatus === "failed") {
            setTimeout(() => { exportTooltipOpen = false; copyStatus = "idle"; }, 3000);
        }
    }

    function handleExportTooltipClickOutside(e: MouseEvent) {
        if (exportTooltipRef && !exportTooltipRef.contains(e.target as Node)) {
            exportTooltipOpen = false;
            copyStatus = "idle";
        }
    }

    $effect(() => {
        if (exportTooltipOpen) {
            document.addEventListener("click", handleExportTooltipClickOutside);
            return () => document.removeEventListener("click", handleExportTooltipClickOutside);
        }
    });

    function playFavorite(track: FavoriteTrack) {
        if (!canPlaySidebar) {
            return;
        }
        onplay(track);
    }

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
        <button class="fav-collapse-toggle" onclick={toggleAllCollapsed} title={allCollapsed ? "Expand all" : "Collapse all"}>
            <svg class="fav-collapse-arrow" class:collapsed={allCollapsed} width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <path d="m6 9 6 6 6-6"/>
            </svg>
            <h4>Favourites <span class="cnt">{$favoriteTracks.length}</span></h4>
        </button>
        <div class="header-btns" bind:this={exportTooltipRef}>
            {#if $favoriteTracks.length > 0}
                <button
                    class="header-btn export-btn"
                    onclick={copyFavouritesText}
                    title="Copy all to clipboard"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                    </svg>
                    {#if showExportLabel}<span class="export-label">Export</span>{/if}
                </button>
                <div class="export-dropdown" bind:this={exportDropdownRef}>
                    <button class="header-btn" onclick={() => exportDropdownOpen = !exportDropdownOpen} title="Download">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                    </button>
                    {#if exportDropdownOpen}
                        <!-- svelte-ignore a11y_click_events_have_key_events -->
                        <!-- svelte-ignore a11y_no_static_element_interactions -->
                        <div class="export-menu" onclick={handleExportClickOutside}>
                            <button class="export-option" onclick={() => { downloadFavouritesJSON(); exportDropdownOpen = false; }}>JSON</button>
                            <button class="export-option" onclick={() => { downloadFavouritesHTML(); exportDropdownOpen = false; }}>HTML</button>
                            <button class="export-option toggle-option" onclick={() => { showExportLabel = !showExportLabel; exportDropdownOpen = false; }}>
                                {showExportLabel ? 'Hide' : 'Show'} label
                            </button>
                        </div>
                    {/if}
                </div>
                <button class="header-btn danger" onclick={clearFavorites} title="Clear all">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                </button>
                {#if exportTooltipOpen}
                    <div class="sidebar-export-tooltip" class:success={copyStatus === "copied"} class:error={copyStatus === "failed"}>
                        {#if copyStatus === "copied"}
                            <div class="export-tooltip-status">✓ Copied {$favoriteTracks.length} tracks</div>
                            <div class="export-tooltip-media">
                                <!-- <img src="/tunemymusic-freetext.png" alt="TuneMyMusic Free Text option" /> -->
                            </div>
                            <a
                                class="export-tooltip-cta"
                                href="https://www.tunemymusic.com/"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
                                </svg>
                                <span class="export-tooltip-cta-text">
                                    Export using TuneMyMusic
                                    <small>Add to Spotify, Apple Music & more</small>
                                </span>
                            </a>
                            <div class="export-tooltip-hint">Click "Free Text", paste, and convert</div>
                        {:else}
                            <div class="export-tooltip-status">✗ Copy failed</div>
                        {/if}
                    </div>
                {/if}
            {/if}
        </div>
    </div>

    {#if !canPlaySidebar}
        <div class="player-status-note">
            {#if $sidebarPlayerStatus === "loading"}
                Spotify preview is still loading.
            {:else}
                Spotify preview is unavailable right now.
            {/if}
        </div>
    {/if}

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
                            class:loading={$sidebarLoadingTrackId === track.track_id}
                            class:disabled={!canPlaySidebar}
                            role="button"
                            tabindex={canPlaySidebar ? 0 : -1}
                            title={canPlaySidebar ? "Play preview" : "Spotify preview is still loading"}
                            onclick={() => playFavorite(track)}
                            onkeydown={(e) => { if (canPlaySidebar && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); playFavorite(track); } }}
                        >
                            {#if $sidebarLoadingTrackId === track.track_id}
                                <span class="loading-icon">
                                    <svg class="spinner" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
                                    </svg>
                                </span>
                            {/if}
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

    .header-btn.export-btn {
        width: auto;
        gap: 0.3rem;
        padding: 0 0.4rem;
        background: var(--gold);
        border-color: var(--gold);
        color: #111;
    }

    .header-btn.export-btn:hover {
        filter: brightness(1.1);
        border-color: var(--gold);
        color: #111;
    }

    .export-label {
        font-size: 0.65rem;
        font-weight: 600;
    }

    .toggle-option {
        border-top: 1px solid var(--border);
        font-size: 0.6rem;
        color: var(--text-3);
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

    .player-status-note {
        font-size: 0.65rem;
        color: var(--text-3);
    }

    .fav-collapse-toggle {
        display: flex;
        align-items: center;
        gap: 0.3rem;
        background: none;
        border: none;
        padding: 0;
        cursor: pointer;
        color: var(--text);
    }

    .fav-collapse-toggle:hover {
        opacity: 0.8;
    }

    .fav-collapse-toggle h4 {
        margin: 0;
        font-size: 0.85rem;
        font-weight: 600;
        white-space: nowrap;
    }

    .fav-collapse-arrow {
        transition: transform 0.2s ease;
        color: var(--text-3);
        flex-shrink: 0;
    }

    .fav-collapse-arrow.collapsed {
        transform: rotate(-90deg);
    }

    .header-btns {
        position: relative;
    }

    .sidebar-export-tooltip {
        position: absolute;
        top: calc(100% + 6px);
        right: 0;
        width: 220px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        padding: 0.65rem;
        z-index: 100;
        animation: tooltipDropIn 0.15s ease-out;
    }

    .sidebar-export-tooltip.error {
        border-color: #a03030;
    }

    .export-tooltip-status {
        font-size: 0.7rem;
        font-weight: 600;
        margin-bottom: 0.4rem;
    }

    .sidebar-export-tooltip.success .export-tooltip-status {
        color: #4ade80;
    }

    .sidebar-export-tooltip.error .export-tooltip-status {
        color: #f87171;
    }

    .export-tooltip-media {
        margin-bottom: 0.4rem;
    }

    .export-tooltip-media:empty {
        display: none;
    }

    .export-tooltip-media img {
        width: 100%;
        border-radius: 4px;
    }

    .export-tooltip-cta {
        display: flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.4rem 0.55rem;
        background: var(--gold);
        color: #111;
        border-radius: 5px;
        font-size: 0.7rem;
        font-weight: 600;
        text-decoration: none;
        transition: filter 0.15s;
    }

    .export-tooltip-cta:hover {
        filter: brightness(1.1);
    }

    .export-tooltip-cta svg {
        flex-shrink: 0;
    }

    .export-tooltip-cta-text {
        display: flex;
        flex-direction: column;
        line-height: 1.3;
    }

    .export-tooltip-cta-text small {
        font-size: 0.55rem;
        font-weight: 400;
        opacity: 0.7;
    }

    .export-tooltip-hint {
        font-size: 0.6rem;
        color: var(--text-3);
        text-align: center;
        margin-top: 0.3rem;
        font-style: italic;
    }

    @keyframes tooltipDropIn {
        from { opacity: 0; transform: translateY(-4px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .player-status-note {
        margin: -0.15rem 0 0.45rem 0;
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
        scrollbar-width: thin;
        scrollbar-color: var(--border) transparent;
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
        scrollbar-width: thin;
        scrollbar-color: var(--border) transparent;
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
    .fav-track.loading { background: var(--gold); color: #111; opacity: 0.7; }
    .fav-track.loading .track-name { color: #111; }
    .fav-track.playing { background: var(--gold); color: #111; }
    .fav-track.playing .track-name { color: #111; }
    .fav-track.playing .remove-btn { color: #333; }
    .fav-track.playing .remove-btn:hover { color: #900; }
    .fav-track.disabled {
        cursor: not-allowed;
        opacity: 0.55;
    }
    .fav-track.disabled:hover {
        background: var(--bg-alt);
    }
    
    .loading-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    
    .spinner {
        animation: spin 1s linear infinite;
    }
    
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

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
