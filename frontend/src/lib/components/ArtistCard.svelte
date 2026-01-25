<script lang="ts">
    import type { Track } from "$lib/stores";
    import { nowPlaying, sidebarPlaying } from "$lib/stores";
    import { onMount } from "svelte";

    interface Props {
        artist: string;
        tracks: Track[];
        onAddToKnown?: () => void;
        onAddToSearch?: () => void;
        onAddFavorite?: (track: Track) => void;
        isKnown?: boolean;
    }

    let {
        artist,
        tracks,
        onAddToKnown,
        onAddToSearch,
        onAddFavorite,
        isKnown = false,
    }: Props = $props();

    let playerEl: HTMLDivElement;
    let controller: any = null;
    let isReady = $state(false);
    let firstTrack = "";
    let currentTrackId = "";
    let showActions = $state(false);
    let isActuallyPlaying = $state(false);

    function getHue(name: string): number {
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            hash = name.charCodeAt(i) + ((hash << 5) - hash);
        }
        return Math.abs(hash) % 360;
    }

    const hue = $derived(getHue(artist));
    const isPlaying = $derived($nowPlaying?.artist === artist);
    const playingTrackId = $derived(isPlaying ? $nowPlaying?.trackId : null);

    onMount(() => {
        firstTrack = tracks[0]?.track_id || "";
        currentTrackId = firstTrack;

        const tryInit = () => {
            const api = (window as any).SpotifyIframeApi;
            if (!api || !playerEl || controller) return;

            api.createController(
                playerEl,
                {
                    width: "100%",
                    height: 80,
                    uri: firstTrack ? `spotify:track:${firstTrack}` : "",
                },
                (c: any) => {
                    controller = c;
                    const w = window as any;
                    w.vibeControllers = w.vibeControllers || {};
                    w.vibeControllers[artist] = c;
                    w.vibeFirstTracks = w.vibeFirstTracks || {};
                    w.vibeFirstTracks[artist] = firstTrack;

                    c.addListener("ready", () => {
                        isReady = true;
                    });
                    c.addListener("playback_update", (e: any) => {
                        isReady = true;
                        isActuallyPlaying = !e.data.isPaused;
                    });
                    setTimeout(() => {
                        isReady = true;
                    }, 3000);
                },
            );
        };

        if ((window as any).SpotifyIframeApi) {
            tryInit();
        } else {
            const h = () => {
                tryInit();
                window.removeEventListener("SpotifyIframeApiReady", h);
            };
            window.addEventListener("SpotifyIframeApiReady", h);
        }

        const resetHandler = (e: CustomEvent) => {
            if (e.detail === artist && controller) {
                controller.pause();
                if (currentTrackId)
                    controller.loadUri(`spotify:track:${currentTrackId}`);
            }
        };
        window.addEventListener("vibeReset", resetHandler as EventListener);
        return () =>
            window.removeEventListener(
                "vibeReset",
                resetHandler as EventListener,
            );
    });

    function play(trackId: string, trackName: string) {
        if (!controller) return;

        const prev = $nowPlaying;

        // Toggle play/pause if clicking the same track
        if (prev?.artist === artist && prev?.trackId === trackId) {
            controller.togglePlay();
            isActuallyPlaying = !isActuallyPlaying;
            return;
        }

        if (prev && prev.artist !== artist) {
            window.dispatchEvent(
                new CustomEvent("vibeReset", { detail: prev.artist }),
            );
        }

        // Pause sidebar player if playing and clear its highlight
        const sidebarCtrl = (window as any).vibeSidebarController;
        if (sidebarCtrl) {
            try {
                sidebarCtrl.pause();
            } catch {}
        }
        sidebarPlaying.set(null);

        currentTrackId = trackId;
        controller.loadUri(`spotify:track:${trackId}`);
        controller.play();
        isActuallyPlaying = true;
        nowPlaying.set({ artist, trackId, trackName });
    }
</script>

<article
    class="card"
    class:known={isKnown}
    style:--hue={hue}
    onmouseenter={() => (showActions = true)}
    onmouseleave={() => (showActions = false)}
>
    <div class="card-header">
        <h3 class="title">{artist}</h3>
        <div class="card-actions" class:visible={showActions}>
            {#if onAddToKnown}
                <button
                    class="action-btn"
                    onclick={onAddToKnown}
                    title={isKnown
                        ? "Already in known list"
                        : "Add to known list"}
                    disabled={isKnown}
                >
                    {isKnown ? "✓" : "👁"}
                </button>
            {/if}
            {#if onAddToSearch}
                <button
                    class="action-btn"
                    onclick={onAddToSearch}
                    title="Add to search"
                >
                    +
                </button>
            {/if}
        </div>
    </div>

    <div class="embed-wrap">
        <div class="embed" bind:this={playerEl}></div>
        <div class="skeleton" class:hide={isReady}></div>
    </div>

    <div class="tracks">
        {#each tracks as t (t.track_id)}
            <div class="trk-row">
                <button
                    class="trk"
                    class:playing={playingTrackId === t.track_id}
                    onclick={() => play(t.track_id, t.track_name)}
                >
                    <span class="ico"
                        >{playingTrackId === t.track_id && isActuallyPlaying
                            ? "❚❚"
                            : "♪"}</span
                    >
                    <span class="txt">{t.track_name}</span>
                </button>
                {#if onAddFavorite}
                    <button
                        class="fav-btn"
                        onclick={() => onAddFavorite(t)}
                        title="Add to favourites"
                    >
                        ♥
                    </button>
                {/if}
            </div>
        {/each}
    </div>
</article>

<style>
    .card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 0.85rem;
        overflow: hidden;
        transition: border-color 0.15s;
    }

    .card.known {
        border-color: var(--gold);
        opacity: 0.7;
    }

    .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.6rem;
        min-height: 24px;
    }

    .title {
        font-size: 1rem;
        font-weight: 600;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 1;
    }

    .card-actions {
        display: flex;
        gap: 0.25rem;
        opacity: 0;
        transition: opacity 0.15s;
    }

    .card-actions.visible {
        opacity: 1;
    }

    .action-btn {
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
    }

    .action-btn:hover:not(:disabled) {
        border-color: var(--gold);
        color: var(--text);
    }

    .action-btn:disabled {
        opacity: 0.5;
        cursor: default;
    }

    .embed-wrap {
        position: relative;
        height: 80px;
        border-radius: 10px;
        overflow: hidden;
        background: #121212;
        margin-bottom: 0.6rem;
    }

    .embed {
        position: absolute;
        inset: 0;
    }

    .embed :global(iframe) {
        border: none !important;
        border-radius: 10px !important;
        width: 100% !important;
        height: 80px !important;
        max-height: 80px !important;
        display: block !important;
        overflow: hidden !important;
    }

    .skeleton {
        position: absolute;
        inset: 0;
        background: linear-gradient(
            90deg,
            #181818 0%,
            #2a2a2a 40%,
            #3a3a3a 50%,
            #2a2a2a 60%,
            #181818 100%
        );
        background-size: 200% 100%;
        animation: shimmer 1.4s infinite;
        border-radius: 10px;
        transition: opacity 0.25s;
        pointer-events: none;
    }

    .skeleton.hide {
        opacity: 0;
    }

    @keyframes shimmer {
        from {
            background-position: 200% 0;
        }
        to {
            background-position: -200% 0;
        }
    }

    .tracks {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .trk-row {
        display: flex;
        gap: 0.25rem;
    }

    .trk {
        flex: 1;
        min-width: 0;
        display: flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.45rem 0.6rem;
        border: none;
        border-radius: 5px;
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 26%, 24%) 0%,
            hsl(calc(var(--hue) + 20), 20%, 18%) 100%
        );
        color: #ddd;
        font-size: 0.78rem;
        text-align: left;
        cursor: pointer;
        position: relative;
        transition: filter 0.12s;
    }

    .trk::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 2.5px;
        background: hsl(var(--hue), 50%, 48%);
        border-radius: 2px 0 0 2px;
    }

    .trk:hover {
        filter: brightness(1.1);
    }

    .trk.playing {
        background: linear-gradient(135deg, #1db954, #169c46);
        color: #fff;
    }

    .trk.playing::before {
        background: #fff;
    }

    .ico {
        width: 0.85rem;
        text-align: center;
        font-size: 0.65rem;
        opacity: 0.7;
    }

    .trk.playing .ico {
        opacity: 1;
        letter-spacing: -2px;
    }

    .txt {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .fav-btn {
        width: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 26%, 24%) 0%,
            hsl(calc(var(--hue) + 20), 20%, 18%) 100%
        );
        border: none;
        border-radius: 5px;
        font-size: 0.7rem;
        color: #ddd;
        opacity: 0.7;
        transition: opacity 0.12s;
    }

    .fav-btn:hover {
        opacity: 1;
        color: #ff6b8a;
    }

    @media (prefers-color-scheme: light) {
        .trk {
            background: linear-gradient(
                135deg,
                hsl(var(--hue), 20%, 38%) 0%,
                hsl(calc(var(--hue) + 20), 16%, 32%) 100%
            );
        }

        .fav-btn {
            background: linear-gradient(
                135deg,
                hsl(var(--hue), 20%, 38%) 0%,
                hsl(calc(var(--hue) + 20), 16%, 32%) 100%
            );
        }
    }

    :global([data-theme="light"]) .trk {
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 20%, 38%) 0%,
            hsl(calc(var(--hue) + 20), 16%, 32%) 100%
        );
    }

    :global([data-theme="light"]) .fav-btn {
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 20%, 38%) 0%,
            hsl(calc(var(--hue) + 20), 16%, 32%) 100%
        );
    }

    @media (hover: none) {
        .card-actions {
            opacity: 1;
        }
    }
</style>
