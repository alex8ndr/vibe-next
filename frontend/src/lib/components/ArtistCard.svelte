<script lang="ts">
    import type { Track } from "$lib/stores";
    import { nowPlaying } from "$lib/stores";
    import { onMount } from "svelte";

    interface Props {
        artist: string;
        tracks: Track[];
    }

    let { artist, tracks }: Props = $props();

    let playerEl: HTMLDivElement;
    let controller: any = null;
    let isReady = $state(false);
    let firstTrack = "";

    function getHue(name: string): number {
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            hash = name.charCodeAt(i) + ((hash << 5) - hash);
        }
        return Math.abs(hash) % 360;
    }

    const hue = getHue(artist);
    const isPlaying = $derived($nowPlaying?.artist === artist);
    const playingTrackId = $derived(isPlaying ? $nowPlaying?.trackId : null);

    onMount(() => {
        firstTrack = tracks[0]?.track_id || "";

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
                    c.addListener("playback_update", () => {
                        isReady = true;
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
                if (firstTrack)
                    controller.loadUri(`spotify:track:${firstTrack}`);
            }
        };
        window.addEventListener("vibeReset", resetHandler as EventListener);
        return () =>
            window.removeEventListener(
                "vibeReset",
                resetHandler as EventListener,
            );
    });

    function play(trackId: string) {
        if (!controller) return;

        const prev = $nowPlaying;

        if (prev?.artist === artist && prev?.trackId === trackId) {
            controller.togglePlay();
            nowPlaying.set(null);
            return;
        }

        if (prev && prev.artist !== artist) {
            window.dispatchEvent(
                new CustomEvent("vibeReset", { detail: prev.artist }),
            );
        }

        controller.loadUri(`spotify:track:${trackId}`);
        controller.play();
        nowPlaying.set({ artist, trackId });
    }
</script>

<article class="card" style:--hue={hue}>
    <h3 class="title">{artist}</h3>

    <div class="embed">
        <div class="player" bind:this={playerEl}></div>
        <div class="skeleton" class:hidden={isReady}></div>
    </div>

    <div class="tracks">
        {#each tracks as t (t.track_id)}
            <button
                class="btn"
                class:active={playingTrackId === t.track_id}
                onclick={() => play(t.track_id)}
            >
                <span class="ico"
                    >{playingTrackId === t.track_id ? "❚❚" : "♪"}</span
                >
                <span class="txt">{t.track_name}</span>
            </button>
        {/each}
    </div>
</article>

<style>
    .card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1rem;
    }

    .title {
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 0.75rem;
        color: var(--text-primary);
    }

    .embed {
        position: relative;
        height: 80px;
        border-radius: 12px;
        overflow: hidden;
        background: #121212;
        margin-bottom: 0.75rem;
    }

    .player {
        width: 100%;
        height: 100%;
    }

    .player :global(iframe) {
        border: none;
        border-radius: 12px;
    }

    .skeleton {
        position: absolute;
        inset: 0;
        background: linear-gradient(
            90deg,
            #181818 0%,
            #2e2e2e 40%,
            #444 50%,
            #2e2e2e 60%,
            #181818 100%
        );
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
        border-radius: 12px;
        transition: opacity 0.3s ease-out;
        pointer-events: none;
    }

    .skeleton.hidden {
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
        gap: 0.3rem;
    }

    .btn {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.55rem 0.75rem;
        border: none;
        border-radius: 6px;
        background: linear-gradient(
            135deg,
            hsl(var(--hue), 30%, 22%) 0%,
            hsl(calc(var(--hue) + 30), 25%, 16%) 100%
        );
        color: #ddd;
        font-size: 0.85rem;
        text-align: left;
        cursor: pointer;
        position: relative;
        transition: filter 0.15s;
    }

    .btn::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 3px;
        background: hsl(var(--hue), 60%, 50%);
        border-radius: 3px 0 0 3px;
    }

    .btn:hover {
        filter: brightness(1.15);
    }

    .btn.active {
        background: linear-gradient(135deg, #1db954, #169c46);
        color: #fff;
    }

    .btn.active::before {
        background: #fff;
    }

    .ico {
        width: 1rem;
        text-align: center;
        font-size: 0.75rem;
        opacity: 0.7;
    }

    .btn.active .ico {
        opacity: 1;
        letter-spacing: -2px;
    }

    .txt {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    @media (prefers-color-scheme: light) {
        .btn {
            background: linear-gradient(
                135deg,
                hsl(var(--hue), 25%, 35%) 0%,
                hsl(calc(var(--hue) + 30), 20%, 28%) 100%
            );
        }
    }
</style>
