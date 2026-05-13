<script lang="ts">
    import { artistsList } from "$lib/stores";
    import { fetchArtists } from "$lib/api";

    interface Props {
        selected?: string[];
        onchange?: (artists: string[]) => void;
        max?: number;
        placeholder?: string;
    }

    let {
        selected = $bindable([]),
        onchange,
        max = 5,
        placeholder = "Search artists...",
    }: Props = $props();

    let query = $state("");
    let isOpen = $state(false);
    let searchResults = $state<string[]>([]);
    let isSearching = $state(false);
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    let searchSeq = 0;
    let abortController: AbortController | null = null;

    const filtered = $derived.by(() => {
        if (query.trim()) {
            return searchResults;
        }
        const q = query.toLowerCase();
        return $artistsList
            .filter((a) => a.toLowerCase().includes(q))
            .slice(0, 100);
    });

    $effect(() => {
        const q = query.trim();
        if (debounceTimer) clearTimeout(debounceTimer);
        abortController?.abort();

        if (q.length < 2) {
            searchResults = [];
            isSearching = false;
            return;
        }
        isSearching = true;
        const seq = ++searchSeq;
        debounceTimer = setTimeout(async () => {
            abortController = new AbortController();
            try {
                const results = await fetchArtists(q, 100, abortController.signal);
                if (seq === searchSeq) {
                    searchResults = results;
                }
            } catch (e: any) {
                if (e?.name !== "AbortError") {
                    console.error("Artist search failed:", e);
                    if (seq === searchSeq) {
                        searchResults = [];
                    }
                }
            } finally {
                if (seq === searchSeq) {
                    isSearching = false;
                }
            }
        }, 250);

        return () => {
            if (debounceTimer) clearTimeout(debounceTimer);
            abortController?.abort();
        };
    });

    function toggle(artist: string) {
        if (selected.includes(artist)) {
            // Removing - keep dropdown open
            selected = selected.filter((a) => a !== artist);
            onchange?.(selected);
        } else if (selected.length < max) {
            // Adding - close dropdown
            selected = [...selected, artist];
            onchange?.(selected);
            query = "";
            isOpen = false;
        }
    }

    function remove(artist: string) {
        selected = selected.filter((a) => a !== artist);
        onchange?.(selected);
    }

    function clearAll() {
        selected = [];
        query = "";
        isOpen = false;
        onchange?.(selected);
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && filtered.length > 0) {
            e.preventDefault();
            toggle(filtered[0]);
        }
        if (e.key === "Escape") {
            isOpen = false;
            query = "";
        }
        if (e.key === "Backspace" && query === "" && selected.length > 0) {
            remove(selected[selected.length - 1]);
        }
    }
</script>

<div class="wrapper">
    <div class="input-box" class:has-clear={selected.length > 0}>
        {#each selected as artist (artist)}
            <button class="chip" onclick={() => remove(artist)} title="Remove {artist}">
                {artist}
                <span class="x">×</span>
            </button>
        {/each}

        {#if selected.length < max}
            <div style="flex: 1; min-width: 80px; display: flex;">
                <input
                    type="text"
                    bind:value={query}
                    {placeholder}
                    onkeydown={handleKeydown}
                    onfocus={() => (isOpen = true)}
                    onblur={() => setTimeout(() => (isOpen = false), 120)}
                />
            </div>
        {/if}
        {#if selected.length === max}
            <span class="limit-badge">{max}/{max}</span>
        {/if}
        {#if selected.length > 0}
            <button class="clear-all" onclick={clearAll} title="Clear all artists" aria-label="Clear all artists"></button>
        {/if}
    </div>

    {#if isOpen}
        {#if isSearching}
            <ul class="list">
                <li><span class="loading">Searching...</span></li>
            </ul>
        {:else if filtered.length > 0}
            <ul class="list">
                {#each filtered as artist (artist)}
                    {@const isSelected = selected.includes(artist)}
                    <li>
                        <button class:selected={isSelected} onmousedown={() => toggle(artist)}>
                            {#if isSelected}<span class="check">✓</span>{/if}
                            {artist}
                        </button>
                    </li>
                {/each}
            </ul>
        {/if}
    {/if}
</div>

<style>
    .wrapper {
        position: relative;
        flex: 1;
        width: 100%;
    }

    .input-box {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem;
        padding: 0.5rem 0.65rem;
        background: var(--bg-alt);
        border: 1px solid var(--border);
        border-radius: 8px;
        min-height: 42px;
        align-items: center;
    }

    .input-box {
        position: relative;
    }

    .input-box.has-clear {
        padding-right: 2.35rem;
    }

    .input-box:focus-within {
        border-color: var(--gold);
        box-shadow: 0 0 0 2px var(--gold-glow);
    }

    .limit-badge {
        position: absolute;
        bottom: 4px;
        right: 36px;
        font-size: 0.6rem;
        color: var(--text-3);
        font-weight: 600;
        pointer-events: none;
    }

    .clear-all {
        position: absolute;
        top: 50%;
        right: 0.55rem;
        transform: translateY(-50%);
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: 1px solid var(--border);
        border-radius: 50%;
        color: var(--text-3);
        cursor: pointer;
    }

    .clear-all::before,
    .clear-all::after {
        content: "";
        position: absolute;
        width: 9px;
        height: 1.5px;
        background: currentColor;
        border-radius: 999px;
    }

    .clear-all::before {
        transform: rotate(45deg);
    }

    .clear-all::after {
        transform: rotate(-45deg);
    }

    .clear-all:hover {
        border-color: var(--gold);
        color: var(--text);
    }

    .chip {
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.2rem 0.45rem;
        background: var(--gold);
        color: #111;
        border: none;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 500;
        max-width: 150px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        cursor: pointer;
        transition: filter 0.2s;
    }

    .chip:hover {
        filter: brightness(0.9);
    }

    .x {
        background: none;
        border: none;
        color: inherit;
        font-size: 1rem;
        line-height: 1;
        padding: 0;
        opacity: 0.7;
    }

    .x:hover {
        opacity: 1;
    }

    input {
        width: 100%;
        min-width: 0;
        background: transparent;
        border: none;
        color: var(--text);
        font-size: 0.875rem;
        outline: none;
    }

    input::placeholder {
        color: var(--text-3);
    }

    .list {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        margin-top: 4px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        max-height: 220px;
        overflow-y: auto;
        z-index: 1000;
        list-style: none;
        box-shadow: 0 6px 16px var(--shadow);
    }

    @media (max-width: 768px) {
        .wrapper {
            position: relative;
        }

        .list {
            position: absolute;
            left: 0;
            right: 0;
            top: 100%;
            bottom: auto;
            margin-top: 4px;
            max-height: 40vh;
            border-radius: 12px;
            z-index: 9999;
        }
    }

    .list button {
        width: 100%;
        padding: 0.55rem 0.7rem;
        background: none;
        border: none;
        color: var(--text);
        font-size: 0.85rem;
        text-align: left;
    }

    .list button:hover {
        background: var(--bg-alt);
    }

    .list button.selected {
        background: var(--gold-glow);
        color: var(--gold);
    }

    .check {
        margin-right: 0.4rem;
        color: var(--gold);
    }

    .loading {
        display: block;
        padding: 0.55rem 0.7rem;
        color: var(--text-3);
        font-size: 0.85rem;
    }

    .list li:first-child button {
        border-radius: 8px 8px 0 0;
    }

    .list li:last-child button {
        border-radius: 0 0 8px 8px;
    }
</style>
