<script lang="ts">
    import { artistsList } from "$lib/stores";

    interface Props {
        selected: string[];
        onchange: (artists: string[]) => void;
        max?: number;
        placeholder?: string;
    }

    let {
        selected = [],
        onchange,
        max = 5,
        placeholder = "Search artists...",
    }: Props = $props();

    let query = $state("");
    let isOpen = $state(false);

    const filtered = $derived.by(() => {
        //if (query.length < 1) return [];
        const q = query.toLowerCase();
        return $artistsList
            .filter((a) => a.toLowerCase().includes(q) && !selected.includes(a))
            .slice(0, 15);
    });

    function add(artist: string) {
        if (selected.length < max && !selected.includes(artist)) {
            onchange([...selected, artist]);
        }
        query = "";
        isOpen = false;
    }

    function remove(artist: string) {
        onchange(selected.filter((a) => a !== artist));
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && filtered.length > 0) {
            e.preventDefault();
            add(filtered[0]);
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
    <div class="input-area">
        {#each selected as artist (artist)}
            <span class="tag">
                {artist}
                <button class="remove" onclick={() => remove(artist)}>×</button>
            </span>
        {/each}

        {#if selected.length < max}
            <input
                type="text"
                bind:value={query}
                {placeholder}
                onkeydown={handleKeydown}
                onfocus={() => (isOpen = true)}
                onblur={() => setTimeout(() => (isOpen = false), 120)}
            />
        {/if}
    </div>

    {#if isOpen && filtered.length > 0}
        <ul class="dropdown">
            {#each filtered as artist (artist)}
                <li>
                    <button onmousedown={() => add(artist)}>{artist}</button>
                </li>
            {/each}
        </ul>
    {/if}
</div>

<style>
    .wrapper {
        position: relative;
    }

    .input-area {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        padding: 0.6rem 0.75rem;
        background: var(--bg-input);
        border: 1px solid var(--border);
        border-radius: 8px;
        min-height: 44px;
        align-items: center;
    }

    .input-area:focus-within {
        border-color: var(--gold);
        box-shadow: 0 0 0 2px var(--gold-glow);
    }

    .tag {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        padding: 0.25rem 0.5rem;
        background: var(--gold);
        color: #111;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 500;
    }

    .remove {
        background: none;
        border: none;
        color: inherit;
        font-size: 1rem;
        line-height: 1;
        padding: 0;
        opacity: 0.7;
    }

    .remove:hover {
        opacity: 1;
    }

    input {
        flex: 1;
        min-width: 100px;
        background: transparent;
        border: none;
        color: var(--text-primary);
        font-size: 0.9rem;
        outline: none;
    }

    input::placeholder {
        color: var(--text-muted);
    }

    .dropdown {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        margin-top: 4px;
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 8px;
        max-height: 240px;
        overflow-y: auto;
        z-index: 50;
        list-style: none;
        box-shadow: 0 4px 12px var(--shadow-lg);
    }

    .dropdown button {
        width: 100%;
        padding: 0.6rem 0.75rem;
        background: none;
        border: none;
        color: var(--text-primary);
        font-size: 0.875rem;
        text-align: left;
    }

    .dropdown button:hover {
        background: var(--bg-secondary);
    }

    .dropdown li:first-child button {
        border-radius: 8px 8px 0 0;
    }

    .dropdown li:last-child button {
        border-radius: 0 0 8px 8px;
    }
</style>
