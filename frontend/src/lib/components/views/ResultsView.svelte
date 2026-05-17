<script lang="ts">
    import ArtistSelect from "$lib/components/ArtistSelect.svelte";
    import ArtistCard from "$lib/components/ArtistCard.svelte";
    import UserLibrary from "$lib/components/UserLibrary.svelte";
    import VibeControls from "$lib/components/VibeControls.svelte";
    import { generateHTML } from "$lib/utils/htmlExport";
    import {
        recommendations,
        recommendationsMeta,
        isLoading,
        loadingProgress,
        progressPhase,
        settings,
        knownArtists,
        favoriteTracks,
        rightPanelOpen,
        sidebarPlaying,
        mobileSidebarOpen,
        devSettings,
        LIMITS,
        DEFAULT_SETTINGS,
        type Track,
        type FavoriteTrack,
    } from "$lib/stores";
    import { trackAddKnown, trackRemoveKnown } from "$lib/analytics";
    import { onMount } from "svelte";
    import { driver } from "driver.js";
    import "driver.js/dist/driver.css";

    let {
        selected = $bindable(),
        fineTune = $bindable(),
        artistTracks,
        lastSearchParams = "",
        hitArtistLimit = false,
        regenerationHistory = new Set(),
        onsearch,
        onregenerate,
        onplay,
    } = $props<{
        selected: string[];
        fineTune: Record<string, string[]>;
        artistTracks: Record<string, Track[]>;
        lastSearchParams?: string;
        hitArtistLimit?: boolean;
        regenerationHistory?: Set<string>;
        onsearch: () => void | Promise<void>;
        onregenerate: () => void;
        onplay: (track: FavoriteTrack) => void;
    }>();

    // Local state
    let expandedArtists = $state<Set<string>>(new Set());
    let globalSongSearch = $state("");

    // Derived
    const currentParams = $derived(JSON.stringify({ selected, fineTune, targetLanguage: $settings.targetLanguage, targetGenre: $settings.targetGenre }));
    const paramsChanged = $derived(lastSearchParams !== "" && currentParams !== lastSearchParams);
    const atMaxArtists = $derived(selected.length >= LIMITS.MAX_INPUT_ARTISTS);
    const hasRecommendations = $derived(Object.keys($recommendations).length > 0);
    const hasFineTuneSelections = $derived(
        (Object.values(fineTune) as string[][]).some(tracks => tracks.length > 0)
    );
    const canRegenerate = $derived(
        hasRecommendations && ($recommendationsMeta?.has_more_candidates ?? true)
    );
    const genreProfiles = $derived($recommendationsMeta?.genre_profiles);
    const inputGenreProfile = $derived($recommendationsMeta?.input_genre_profile);
    const inputLanguageProfile = $derived($recommendationsMeta?.input_language_profile);
    const searchVectorAudio = $derived($recommendationsMeta?.search_vector_audio);
    const searchVectorGenre = $derived($recommendationsMeta?.search_vector_genre);
    const totalTracks = $derived(Object.values($recommendations).reduce((sum, tracks) => sum + tracks.length, 0));
    
    // Helper to format genre profile for display
    function formatGenreProfile(genres: Array<{genre: string, pct: number}>): string {
        return genres.map(g => `${Math.round(g.pct)}% ${g.genre}`).join(', ');
    }
    
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

    function clearSongs(artist: string) {
        const { [artist]: _removed, ...rest } = fineTune;
        fineTune = rest;
    }

    function clearAllSongs() {
        fineTune = {};
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
        if (window.confirm('Reset customize settings to defaults?')) {
            settings.set(DEFAULT_SETTINGS);
        }
    }

    function addToKnown(artist: string) {
        knownArtists.update((list) => {
            if (list.includes(artist)) {
                trackRemoveKnown(artist);
                return list.filter(a => a !== artist);
            }
            trackAddKnown(artist);
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

    

    let hoveredSeed = $state<{name: string, artist: string, x: number, y: number, hue: number, features: Record<string, number>} | null>(null);

    function getHue(name: string): number {
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            hash = name.charCodeAt(i) + ((hash << 5) - hash);
        }
        return Math.abs(hash) % 360;
    }

    function seedCoords(af: Record<string, number>): { x: number; y: number } {
        return { x: Number(af.energy ?? 0.5), y: Number(af.valence ?? 0.5) };
    }

    const seedPoints = $derived.by(() => {
        const points: Array<{name: string, artist: string, x: number, y: number, hue: number, features: Record<string, number>, dimmed: boolean}> = [];
        for (const artist of selected) {
            const tracks = artistTracks[artist] || [];
            const seedTrackIds = fineTune[artist] || [];
            const hasFineTune = seedTrackIds.length > 0;
            for (const t of tracks) {
                if (!t.audio_features) continue;
                const af = t.audio_features as Record<string, number>;
                const { x, y } = seedCoords(af);
                const isSelected = !hasFineTune || seedTrackIds.includes(t.track_id);
                points.push({
                    name: t.track_name,
                    artist,
                    x, y,
                    hue: getHue(artist),
                    features: af,
                    dimmed: hasFineTune && !isSelected,
                });
            }
        }
        return points;
    });

    let exportStatus = $state<"idle" | "copied" | "failed">("idle");
    let exportTooltipOpen = $state(false);
    let exportTooltipRef = $state<HTMLDivElement | null>(null);
    let downloadDropdownOpen = $state(false);
    let downloadDropdownRef = $state<HTMLDivElement | null>(null);

    async function exportResults() {
        const text = Object.entries($recommendations)
            .flatMap(([artist, tracks]) =>
                tracks.map((t) => `${artist} - ${t.track_name}`)
            )
            .join("\n");
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            exportStatus = "copied";
        } catch {
            exportStatus = "failed";
        }
        exportTooltipOpen = true;
        if (exportStatus === "failed") {
            setTimeout(() => { exportTooltipOpen = false; exportStatus = "idle"; }, 3000);
        }
    }

    function handleExportTooltipClickOutside(e: MouseEvent) {
        if (exportTooltipRef && !exportTooltipRef.contains(e.target as Node)) {
            exportTooltipOpen = false;
            exportStatus = "idle";
        }
    }

    $effect(() => {
        if (exportTooltipOpen) {
            document.addEventListener("click", handleExportTooltipClickOutside);
            return () => document.removeEventListener("click", handleExportTooltipClickOutside);
        }
    });

    function handleDownloadClickOutside(e: MouseEvent) {
        if (downloadDropdownRef && !downloadDropdownRef.contains(e.target as Node)) {
            downloadDropdownOpen = false;
        }
    }

    $effect(() => {
        if (downloadDropdownOpen) {
            document.addEventListener("click", handleDownloadClickOutside);
            return () => document.removeEventListener("click", handleDownloadClickOutside);
        }
    });

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

    function downloadTXT() {
        const text = Object.entries($recommendations)
            .flatMap(([artist, tracks]) =>
                tracks.map((t) => `${artist} - ${t.track_name}`)
            )
            .join("\n");
        if (!text) return;
        const blob = new Blob([text], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "vibe-recommendations.txt";
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

    onMount(() => {
        const hasSeenTour = localStorage.getItem("vibeTourSeen");
        if (!hasSeenTour) {
            setTimeout(() => {
                startTour();
                localStorage.setItem("vibeTourSeen", "true");
            }, 500);
        }
    });

    function startTour() {
        const firstCard = document.querySelector('.grid .card') as HTMLElement | null;
        const target = document.getElementById('tour-results-target');
        if (firstCard && target) {
            target.style.height = `${firstCard.offsetHeight}px`;
        }

        const steps = [
            { element: '.tour-results-target', popover: { title: 'Results', description: 'Explore your tailored artist recommendations and their tracks.', side: "bottom", align: 'start' } },
            { element: '.trk', popover: { title: 'Listen', description: 'Click on a track to listen to it. Click again to pause.', side: "bottom", align: 'start' } },
            { element: '.fav-btn', popover: { title: 'Favorite', description: 'Favorite a track if you like it.', side: "bottom", align: 'start' } },
            { element: '.btn-regenerate', popover: { title: 'Regenerate', description: 'Want more? Click here to get a fresh batch of recommendations for the same input.', side: "bottom", align: 'start' } },
            { element: '.side-search', popover: { title: 'Add Artists', description: 'Search and add artists to serve as the foundation for your next recommendations.', side: "right", align: 'start' } },
            selected.length > 0 ? { element: '.fine-tune-section', popover: { title: 'Fine-tune', description: 'Select specific songs from your chosen artists to narrow down the vibe.', side: "right", align: 'start' } } : null,
            { element: '.customize-section', popover: { title: 'Customize Vibe', description: 'Adjust number of recommended artists and songs, and other audio features.', side: "right", align: 'start' } },
            { element: '.btn-update', popover: { title: 'Update', description: 'Click update to generate new recommendations.', side: "right", align: 'start' } },
        ].filter(Boolean);

        const d = driver({
            showProgress: true,
            animate: true,
            steps: steps as any
        });
        d.drive();
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
        <div class="btn-row">
            <button
                class="btn-update"
                data-phase={$progressPhase}
                style:--progress={$loadingProgress / 100}
                onclick={() => onsearch()}
                disabled={!selected.length || $isLoading}
            >
                <span class="btn-label">Discover</span>
            </button>
            <button
                class="btn-regenerate"
                class:spinning={$isLoading}
                onclick={onregenerate}
                disabled={!canRegenerate || $isLoading || paramsChanged || hitArtistLimit}
                title={hitArtistLimit || paramsChanged ? "Update search first" : canRegenerate ? "Regenerate with different artists" : "No more alternatives available"}
            >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>
                </svg>
            </button>
        </div>

        {#if selected.length > 0}
            <div class="side-section fine-tune-section">
                <div class="fine-header">
                    <h4>Fine-tune</h4>
                    {#if hasFineTuneSelections}
                        <button 
                            class="clear-songs-btn clear-header-songs-btn" 
                            onclick={clearAllSongs}
                            title="Clear all selected songs"
                            aria-label="Clear all selected songs"
                        >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                            </svg>
                        </button>
                    {/if}
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
                                        ).includes(t.track_id)}
                                        {@const atLimit =
                                            isAtSongLimit(artist)}
                                        <button
                                            class="ss"
                                            class:on={sel}
                                            class:disabled={!sel && atLimit}
                                            onclick={() =>
                                                toggleSong(
                                                    artist,
                                                    t.track_id,
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
                                        <span class="muted">No matches for search</span>
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

        <!-- Seed map scatter plot in dev mode -->
        {#if import.meta.env.DEV && $devSettings.debugMode && $settings.showAudioFeatures && seedPoints.length > 0}
            <div class="side-section seed-map-section">
                <div class="chart-header">
                    <h5>Seed Map</h5>
                </div>
                <div class="seed-map-wrap">
                    <svg viewBox="-12 -5 117 117" class="seed-map-svg">
                        {#each [0, 25, 50, 75, 100] as v}
                            <line x1={v} y1="0" x2={v} y2="100" stroke="var(--border)" stroke-width="0.3" />
                            <line x1="0" y1={v} x2="100" y2={v} stroke="var(--border)" stroke-width="0.3" />
                        {/each}
                        <!-- X-axis tick labels (Energy) -->
                        {#each [{v: 0, l: '0'}, {v: 50, l: '.5'}, {v: 100, l: '1'}] as tick}
                            <text x={tick.v} y="106" text-anchor="middle" fill="var(--text-3)" font-size="3.5">{tick.l}</text>
                        {/each}
                        <!-- Y-axis tick labels (Mood) - note: SVG y is inverted -->
                        {#each [{v: 100, l: '0'}, {v: 50, l: '.5'}, {v: 0, l: '1'}] as tick}
                            <text x="-3" y={tick.v + 1.5} text-anchor="end" fill="var(--text-3)" font-size="3.5">{tick.l}</text>
                        {/each}
                        <text x="50" y="112" text-anchor="middle" fill="var(--text-3)" font-size="3.5">Energy →</text>
                        <text x="-8" y="50" text-anchor="middle" fill="var(--text-3)" font-size="3.5" transform="rotate(-90, -8, 50)">Valence →</text>
                        {#if searchVectorAudio}
                            {@const sv = seedCoords(searchVectorAudio as Record<string, number>)}
                            {@const svx = sv.x * 100}
                            {@const svy = 100 - sv.y * 100}
                            <line x1={svx - 4} y1={svy} x2={svx + 4} y2={svy} stroke="var(--gold)" stroke-width="1" />
                            <line x1={svx} y1={svy - 4} x2={svx} y2={svy + 4} stroke="var(--gold)" stroke-width="1" />
                        {/if}
                        {#each seedPoints.filter(p => p.dimmed) as pt}
                            <circle
                                cx={pt.x * 100}
                                cy={100 - pt.y * 100}
                                r="2"
                                fill="hsl({pt.hue}, 20%, 40%)"
                                opacity="0.3"
                                style="cursor: pointer;"
                                onmouseenter={() => hoveredSeed = pt}
                                onmouseleave={() => hoveredSeed = null}
                            />
                        {/each}
                        {#each seedPoints.filter(p => !p.dimmed) as pt}
                            <circle
                                cx={pt.x * 100}
                                cy={100 - pt.y * 100}
                                r={hoveredSeed === pt ? 4 : 3}
                                fill="hsl({pt.hue}, 60%, 55%)"
                                stroke="hsl({pt.hue}, 40%, 35%)"
                                stroke-width="0.5"
                                style="cursor: pointer;"
                                onmouseenter={() => hoveredSeed = pt}
                                onmouseleave={() => hoveredSeed = null}
                            />
                        {/each}
                    </svg>
                    {#if hoveredSeed}
                        <div class="seed-tooltip">
                            <strong>{hoveredSeed.name}</strong>
                            <span class="seed-tooltip-artist">{hoveredSeed.artist}</span>
                            <div class="seed-tooltip-features">
                                {#each Object.entries(hoveredSeed.features).filter(([k]) => typeof hoveredSeed?.features[k] === 'number') as [key, val]}
                                    <span>{key}: {Number(val).toFixed(2)}</span>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </div>
                <div class="seed-legend">
                    {#each selected as artist}
                        <span class="seed-legend-item">
                            <span class="seed-dot" style="background: hsl({getHue(artist)}, 60%, 55%)"></span>
                            {artist}
                        </span>
                    {/each}
                    <span class="seed-legend-item">
                        <span class="seed-dot seed-dot-vector"></span>
                        Vector
                    </span>
                </div>
            </div>
        {/if}

        <!-- Dev mode section: only visible in dev builds -->
        {#if import.meta.env.DEV}
            <div class="side-section dev-section">
                <div class="dev-header">
                    <h4>🛠 Dev</h4>
                </div>
                <label class="dev-toggle">
                    <input type="checkbox" bind:checked={$devSettings.debugMode} />
                    <span>Debug</span>
                </label>
                {#if $devSettings.debugMode}
                    <div class="dev-pool-status">
                        <div class="pool-stat"><span>Regen:</span> <strong>{regenerationHistory?.size ?? 0}</strong></div>
                        <div class="pool-stat"><span>Params:</span> <strong>{paramsChanged ? "⚠" : "✓"}</strong></div>
                        <div class="pool-stat"><span>More:</span> <strong>{$recommendationsMeta?.has_more_candidates ? "✓" : "✗"}</strong></div>
                    </div>
                {/if}
            </div>
        {/if}
    </aside>

    <section class="main-results">
        <div class="results-header">
            <h2>{Object.keys($recommendations).length} artists, {totalTracks} songs</h2>
            {#if $devSettings.debugMode && inputGenreProfile && inputGenreProfile.length > 0}
                <div class="debug-input-profile">
                    <span class="debug-label">Input profile:</span>
                    {#each inputGenreProfile as { artist, genres }}
                        {@const langEntry = inputLanguageProfile?.find(l => l.artist === artist)}
                        <span class="debug-artist-profile">
                            {artist}: {formatGenreProfile(genres)}{#if langEntry} · {langEntry.languages.map(l => `${Math.round(l.pct)}% ${l.language}`).join(', ')}{/if}
                        </span>
                    {/each}
                </div>
            {/if}
            {#if $devSettings.debugMode && $settings.showAudioFeatures && searchVectorGenre && searchVectorGenre.length > 0}
                <div class="debug-search-vector">
                    <span class="debug-label">Genre vector:</span>
                    {#each searchVectorGenre as {genre, pct}}
                        <span class="debug-feature">{genre}: {pct.toFixed(1)}%</span>
                    {/each}
                </div>
            {/if}
            <div class="results-actions" bind:this={exportTooltipRef}>
                <button
                    class="btn-action"
                    onclick={startTour}
                    title="Take a tour of the interface"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                    Tour
                </button>
                <button
                    class="btn-export"
                    onclick={exportResults}
                    disabled={!hasRecommendations}
                    title="Copy all results to clipboard"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                    </svg>
                    Export
                </button>
                <div class="download-dropdown" bind:this={downloadDropdownRef}>
                    <button
                        class="btn-action"
                        onclick={() => downloadDropdownOpen = !downloadDropdownOpen}
                        disabled={!hasRecommendations}
                        title="Download results"
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                        </svg>
                        <svg class="chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <path d="m6 9 6 6 6-6"/>
                        </svg>
                    </button>
                    {#if downloadDropdownOpen}
                        <div class="download-menu">
                            <button class="download-option" onclick={() => { downloadTXT(); downloadDropdownOpen = false; }}>TXT</button>
                            <button class="download-option" onclick={() => { downloadHTML(); downloadDropdownOpen = false; }}>HTML</button>
                            <button class="download-option" onclick={() => { downloadJSON(); downloadDropdownOpen = false; }}>JSON</button>
                        </div>
                    {/if}
                </div>
                {#if exportTooltipOpen}
                    <div class="export-tooltip" class:success={exportStatus === "copied"} class:error={exportStatus === "failed"}>
                        {#if exportStatus === "copied"}
                            <div class="export-tooltip-status">✓ Copied {totalTracks} tracks to clipboard</div>
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
                            <div class="export-tooltip-hint">Click <strong>"Free Text"</strong>, paste, and convert</div>
                        {:else}
                            <div class="export-tooltip-status">✗ Copy failed — try downloading instead</div>
                        {/if}
                    </div>
                {/if}
            </div>
        </div>

        {#if !hasRecommendations}
            <div class="empty-state">
                <p>No recommendations yet.</p>
                <p class="muted">Add artists and click Update to get started.</p>
            </div>
        {:else}
        <div class="grid" style="position: relative;">
            <!-- Invisible target for the tour to cleanly highlight the first row -->
            <div id="tour-results-target" class="tour-results-target" style="position: absolute; top: 0; left: 0; right: 0; height: 310px; pointer-events: none; z-index: -1;"></div>
            {#each Object.entries($recommendations) as [artist, tracks], i (artist + '-' + (tracks[0]?.track_id || ''))}
                <ArtistCard 
                    {artist} 
                    {tracks}
                    staggerIndex={i}
                    isKnown={$knownArtists.includes(artist)}
                    isAdded={selected.includes(artist)}
                    onAddToKnown={() => addToKnown(artist)}
                    onAddToSearch={() => addToSearch(artist)}
                    showFavoriteButton={true}
                    genreProfile={genreProfiles?.[artist]}
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
