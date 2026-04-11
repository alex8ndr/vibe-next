<script lang="ts">
    import { settings, LIMITS } from "$lib/stores";
    import { fetchFilters, type FilterOption } from "$lib/api";

    function getVarietyLabel(v: number) {
        if (v === 0) return "None";
        if (v === 1) return "Low";
        if (v === 2) return "Medium";
        return "High";
    }

    function getGenreLabel(v: number) {
        if (v === 0) return "None";
        if (v === 1) return "Low";
        if (v === 2) return "Medium";
        if (v === 3) return "High";
        return "Max";
    }

    // Advanced section state
    let advancedOpen = $state(false);
    let langDropdownOpen = $state(false);
    let genreDropdownOpen = $state(false);
    let langSearch = $state('');
    let genreSearch = $state('');

    // Dynamic filter options loaded from backend
    let dataLanguages = $state<FilterOption[]>([]);
    let dataGenres = $state<FilterOption[]>([]);
    let filtersLoaded = $state(false);

    const languageOptions = $derived<{ value: string; label: string }[]>([
        { value: 'match', label: 'Match input' },
        { value: 'any', label: 'Any' },
        ...dataLanguages.map(f => ({ value: f.value, label: f.label })),
    ]);

    const genreOptions = $derived<{ value: string; label: string }[]>([
        { value: 'match', label: 'Match input' },
        { value: 'any', label: 'Any' },
        ...dataGenres.map(f => ({ value: f.value, label: f.label })),
    ]);

    // Fetch filter options when advanced section is first opened
    $effect(() => {
        if (advancedOpen && !filtersLoaded) {
            filtersLoaded = true;
            fetchFilters().then(f => {
                dataLanguages = f.languages;
                dataGenres = f.genres;
            }).catch(() => {
                // Silently fail — dropdowns will just show match/any
            });
        }
    });

    let filteredLanguages = $derived(
        langSearch
            ? languageOptions.filter(o => o.label.toLowerCase().includes(langSearch.toLowerCase()))
            : languageOptions
    );

    let filteredGenres = $derived(
        genreSearch
            ? genreOptions.filter(o => o.label.toLowerCase().includes(genreSearch.toLowerCase()))
            : genreOptions
    );

    function langDisplayName(value: string): string {
        return languageOptions.find(o => o.value === value)?.label ?? value;
    }

    function genreDisplayName(value: string): string {
        return genreOptions.find(o => o.value === value)?.label ?? value;
    }

    // Close dropdowns on outside click
    $effect(() => {
        if (!langDropdownOpen && !genreDropdownOpen) return;
        function handleClick() {
            langDropdownOpen = false;
            genreDropdownOpen = false;
        }
        const timer = setTimeout(() => window.addEventListener('click', handleClick), 0);
        return () => {
            clearTimeout(timer);
            window.removeEventListener('click', handleClick);
        };
    });
</script>
<!--

<div class="vibe-slider">
    <div class="vibe-labels">
        <span>Chill</span>
        <span>Intense</span>
    </div>
    <input
        type="range"
        min="-1"
        max="1"
        step="0.1"
        bind:value={$settings.vibeMood}
    />
</div>

<div class="vibe-slider">
    <div class="vibe-labels">
        <span>Acoustic</span>
        <span>Electronic</span>
    </div>
    <input
        type="range"
        min="-1"
        max="1"
        step="0.1"
        bind:value={$settings.vibeSound}
    />
</div>

<div class="vibe-slider">
    <div class="vibe-labels">
        <span>Hidden Gems</span>
        <span>Mainstream</span>
    </div>
    <input
        type="range"
        min="-1"
        max="1"
        step="0.1"
        bind:value={$settings.popularity}
    />
</div>
-->

<div class="settings-compact">
    <div class="setting-mini">
        <div class="setting-label-row">
            <span>Variety</span>
            <span class="setting-value">{getVarietyLabel($settings.variety)}</span>
        </div>
        <input type="range" min="0" max="3" bind:value={$settings.variety} />
    </div>
    <div class="setting-mini">
        <div class="setting-label-row">
            <span>Genre Focus</span>
            <span class="setting-value">{getGenreLabel($settings.genreWeight)}</span>
        </div>
        <input type="range" min="0" max="4" step="1" bind:value={$settings.genreWeight} />
    </div>
    <div class="setting-mini">
        <div class="setting-label-row">
            <span>Artists</span>
            <span class="setting-value">{$settings.maxResults}</span>
        </div>
        <input
            type="range"
            min={LIMITS.MAX_RESULT_ARTISTS.min}
            max={LIMITS.MAX_RESULT_ARTISTS.max}
            bind:value={$settings.maxResults}
        />
    </div>
    <div class="setting-mini">
        <div class="setting-label-row">
            <span>Songs</span>
            <span class="setting-value">{$settings.tracksPerArtist}</span>
        </div>
        <input
            type="range"
            min={LIMITS.MAX_TRACKS_PER_ARTIST.min}
            max={LIMITS.MAX_TRACKS_PER_ARTIST.max}
            bind:value={$settings.tracksPerArtist}
        />
    </div>
</div>

<div class="advanced-section">
    <button class="advanced-toggle" onclick={() => advancedOpen = !advancedOpen}>
        <span>Advanced</span>
        <svg class="adv-chevron" class:open={advancedOpen} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="m6 9 6 6 6-6"/>
        </svg>
    </button>
    {#if advancedOpen}
        <div class="advanced-body">
            <!-- Target Language -->
            <div class="adv-field">
                <span class="adv-label">Target Language</span>
                <div class="adv-dropdown" class:open={langDropdownOpen}>
                    <button class="adv-select" class:active={$settings.targetLanguage !== 'match'} onclick={(e) => { e.stopPropagation(); langDropdownOpen = !langDropdownOpen; genreDropdownOpen = false; langSearch = ''; }}>
                        <span>{langDisplayName($settings.targetLanguage)}</span>
                        <svg class="adv-chevron" class:open={langDropdownOpen} width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m6 9 6 6 6-6"/></svg>
                    </button>
                    {#if langDropdownOpen}
                        <div class="adv-menu upward">
                            <input class="adv-search" type="text" placeholder="Search..." bind:value={langSearch} onclick={(e) => e.stopPropagation()} />
                            <div class="adv-options">
                                {#each filteredLanguages as opt}
                                    <button class="adv-option" class:selected={$settings.targetLanguage === opt.value} onclick={(e) => { e.stopPropagation(); settings.update(s => ({...s, targetLanguage: opt.value})); langDropdownOpen = false; }}>
                                        {opt.label}
                                    </button>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </div>
            </div>
            <!-- Target Genre -->
            <div class="adv-field">
                <span class="adv-label">Target Genre</span>
                <div class="adv-dropdown" class:open={genreDropdownOpen}>
                    <button class="adv-select" class:active={$settings.targetGenre !== 'match'} onclick={(e) => { e.stopPropagation(); genreDropdownOpen = !genreDropdownOpen; langDropdownOpen = false; genreSearch = ''; }}>
                        <span>{genreDisplayName($settings.targetGenre)}</span>
                        <svg class="adv-chevron" class:open={genreDropdownOpen} width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m6 9 6 6 6-6"/></svg>
                    </button>
                    {#if genreDropdownOpen}
                        <div class="adv-menu upward">
                            <input class="adv-search" type="text" placeholder="Search..." bind:value={genreSearch} onclick={(e) => e.stopPropagation()} />
                            <div class="adv-options">
                                {#each filteredGenres as opt}
                                    <button class="adv-option" class:selected={$settings.targetGenre === opt.value} onclick={(e) => { e.stopPropagation(); settings.update(s => ({...s, targetGenre: opt.value})); genreDropdownOpen = false; }}>
                                        {opt.label}
                                    </button>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </div>
            </div>
        </div>
    {/if}
</div>

<style>
    /* Vibe sliders - prominent, labeled endpoints */
    .vibe-slider {
        margin-bottom: 0.75rem;
    }

    .vibe-labels {
        display: flex;
        justify-content: space-between;
        font-size: 0.65rem;
        color: var(--text-3);
        margin-bottom: 0.2rem;
    }

    .vibe-slider input[type="range"] {
        width: 100%;
        height: 4px;
        background: linear-gradient(
            to right,
            var(--bg-alt),
            var(--gold-dim),
            var(--bg-alt)
        );
        border-radius: 2px;
        appearance: none;
        outline: none;
    }

    .vibe-slider input[type="range"]::-webkit-slider-thumb {
        appearance: none;
        width: 14px;
        height: 14px;
        background: var(--gold);
        border-radius: 50%;
        cursor: pointer;
        border: 2px solid var(--surface);
    }

    /* Compact settings row */
    .settings-compact {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.5rem 0.75rem;
        margin-top: 0.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid var(--border);
    }

    .setting-mini {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
    }

    .setting-mini span {
        font-size: 0.6rem;
        color: var(--text-3);
    }

    .setting-mini input[type="range"] {
        width: 100%;
        height: 3px;
        background: var(--bg-alt);
        border-radius: 2px;
        appearance: none;
        accent-color: var(--gold);
        outline: none;
    }

    .setting-mini input[type="range"]::-webkit-slider-thumb {
        appearance: none;
        width: 10px;
        height: 10px;
        background: var(--gold);
        border-radius: 50%;
        cursor: pointer;
    }

    .setting-mini input[type="range"]::-moz-range-track {
        height: 3px;
        border-radius: 2px;
        background: var(--bg-alt);
    }

    .setting-mini input[type="range"]::-moz-range-thumb {
        width: 10px;
        height: 10px;
        background: var(--gold);
        border-radius: 50%;
        cursor: pointer;
        border: none;
    }

    .setting-label-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .setting-value {
        font-size: 0.6rem;
        color: var(--gold);
        font-weight: 600;
    }

    /* Advanced section */
    .advanced-section {
        margin-top: 0.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid var(--border);
    }

    .advanced-toggle {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        background: none;
        border: none;
        color: var(--text-3);
        font-size: 0.6rem;
        cursor: pointer;
        padding: 0.15rem 0;
    }

    .advanced-toggle:hover {
        color: var(--text);
    }

    .adv-chevron {
        transition: transform 0.2s ease;
    }

    .adv-chevron.open {
        transform: rotate(180deg);
    }

    .advanced-body {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.5rem 0.75rem;
        margin-top: 0.4rem;
    }

    .adv-field {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
    }

    .adv-label {
        font-size: 0.6rem;
        color: var(--text-3);
    }

    .adv-dropdown {
        position: relative;
    }

    .adv-select {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        padding: 0.25rem 0.4rem;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 4px;
        color: var(--text);
        font-size: 0.6rem;
        cursor: pointer;
    }

    .adv-select:hover {
        border-color: var(--gold-dim);
    }

    .adv-select.active {
        border-color: var(--gold-dim);
        color: var(--gold);
    }

    .adv-menu {
        position: absolute;
        left: 0;
        right: 0;
        z-index: 50;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 4px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        display: flex;
        flex-direction: column;
    }

    .adv-menu.upward {
        bottom: 100%;
        margin-bottom: 2px;
    }

    .adv-search {
        padding: 0.3rem 0.4rem;
        background: var(--bg-alt);
        border: none;
        border-bottom: 1px solid var(--border);
        color: var(--text);
        font-size: 0.6rem;
        outline: none;
    }

    .adv-menu.upward .adv-search {
        border-bottom: 1px solid var(--border);
        border-top: none;
    }

    .adv-options {
        max-height: 160px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
    }

    .adv-option {
        padding: 0.25rem 0.4rem;
        background: none;
        border: none;
        color: var(--text-2);
        font-size: 0.6rem;
        text-align: left;
        cursor: pointer;
    }

    .adv-option:hover {
        background: var(--bg-alt);
        color: var(--text);
    }

    .adv-option.selected {
        color: var(--gold);
        font-weight: 600;
    }
</style>
