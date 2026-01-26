<script lang="ts">
    import { settings, LIMITS } from "$lib/stores";

    function getVarietyLabel(v: number) {
        if (v <= 1) return "None";
        if (v === 2) return "Low";
        if (v === 3) return "Medium";
        return "High";
    }

    function getGenreLabel(v: number) {
        if (v === 0) return "Ignore";
        if (v <= 1) return "Low";
        if (v <= 2) return "Medium";
        if (v <= 3) return "High";
        if (v <= 4) return "Very High";
        return "Max";
    }
</script>

<div class="vibe-slider">
    <div class="vibe-labels">
        <span>Chill</span>
        <span>Energetic</span>
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

<div class="settings-compact">
    <div class="setting-mini">
        <div class="setting-label-row">
            <span>Variety</span>
            <span class="setting-value">{getVarietyLabel($settings.variety)}</span>
        </div>
        <input type="range" min="1" max="4" bind:value={$settings.variety} />
    </div>
    <div class="setting-mini">
        <div class="setting-label-row">
            <span>Genre Focus</span>
            <span class="setting-value">{getGenreLabel($settings.genreWeight)}</span>
        </div>
        <input type="range" min="0" max="4" step="0.5" bind:value={$settings.genreWeight} />
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
</style>
