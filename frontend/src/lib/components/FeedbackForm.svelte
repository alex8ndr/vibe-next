<script lang="ts">
    import { onMount } from "svelte";

    const RECAPTCHA_SITE_KEY = "6LfhnmgsAAAAALuROTUByVLOHcG-B_o9nAKRVuTk";

    let isOpen = $state(false);
    let feedbackType = $state("feedback");
    let message = $state("");
    let email = $state("");
    let submitting = $state(false);
    let submitted = $state(false);
    let error = $state<string | null>(null);
    let captchaToken = $state<string | null>(null);
    let captchaWidgetId = $state<number | null>(null);
    let captchaContainer = $state<HTMLDivElement | null>(null);

    // Dynamic fields for suggestions
    let artistName = $state("");
    let albumName = $state("");
    let tracks = $state<string[]>([""]);

    // Artists list for artist suggestions
    let artists = $state<string[]>([""]);

    onMount(() => {
        if (!document.querySelector('script[src*="recaptcha"]')) {
            const script = document.createElement("script");
            script.src = "https://www.google.com/recaptcha/api.js?render=explicit";
            script.async = true;
            script.defer = true;
            document.head.appendChild(script);
        }
    });

    function getTheme(): "dark" | "light" {
        const dataTheme = document.documentElement.getAttribute("data-theme");
        if (dataTheme) return dataTheme as "dark" | "light";
        return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function renderCaptcha() {
        if (captchaWidgetId !== null || !captchaContainer) return;
        
        const grecaptcha = (window as any).grecaptcha;
        if (!grecaptcha?.render) {
            setTimeout(renderCaptcha, 100);
            return;
        }

        captchaWidgetId = grecaptcha.render(captchaContainer, {
            sitekey: RECAPTCHA_SITE_KEY,
            theme: getTheme(),
            callback: (token: string) => { captchaToken = token; },
            "expired-callback": () => { captchaToken = null; }
        });
    }

    $effect(() => {
        if (isOpen && captchaContainer) {
            renderCaptcha();
        }
    });

    // Reset dynamic fields when type changes
    $effect(() => {
        feedbackType;
        artistName = "";
        albumName = "";
        tracks = [""];
        artists = [""];
        message = "";
    });

    function addTrack() {
        tracks = [...tracks, ""];
    }

    function removeTrack(idx: number) {
        if (tracks.length > 1) {
            tracks = tracks.filter((_, i) => i !== idx);
        }
    }

    function addArtist() {
        artists = [...artists, ""];
    }

    function removeArtist(idx: number) {
        if (artists.length > 1) {
            artists = artists.filter((_, i) => i !== idx);
        }
    }

    function buildMessage(): string {
        if (feedbackType === "artist") {
            const artistList = artists.filter(a => a.trim()).join("\n- ");
            return `Artist Suggestion(s):\n- ${artistList}${message ? `\n\nNotes: ${message}` : ""}`;
        }
        if (feedbackType === "album") {
            const trackList = tracks.filter(t => t.trim()).map((t, i) => `${i + 1}. ${t}`).join("\n");
            return `Album Suggestion:\nArtist: ${artistName}\nAlbum: ${albumName}${trackList ? `\n\nTracks:\n${trackList}` : ""}${message ? `\n\nNotes: ${message}` : ""}`;
        }
        if (feedbackType === "track") {
            const trackList = tracks.filter(t => t.trim()).map((t, i) => `${i + 1}. ${t}`).join("\n");
            return `Track Suggestion:\nArtist: ${artistName}\n\nTracks:\n${trackList}${message ? `\n\nNotes: ${message}` : ""}`;
        }
        return message;
    }

    function isValid(): boolean {
        if (feedbackType === "artist") {
            return artists.some(a => a.trim().length > 0);
        }
        if (feedbackType === "album") {
            return artistName.trim().length > 0 && albumName.trim().length > 0;
        }
        if (feedbackType === "track") {
            return artistName.trim().length > 0 && tracks.some(t => t.trim().length > 0);
        }
        return message.trim().length > 0;
    }

    async function handleSubmit(e: SubmitEvent) {
        e.preventDefault();
        if (!isValid()) return;
        if (!captchaToken) {
            error = "Please complete the captcha";
            return;
        }

        submitting = true;
        error = null;

        try {
            const res = await fetch("https://api.staticforms.xyz/submit", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    accessKey: "sf_blf73j00d7fe0he2im7dgd23",
                    subject: `Vibe Feedback: ${feedbackType}`,
                    message: buildMessage(),
                    replyTo: email || "noreply@vibe.app",
                    "g-recaptcha-response": captchaToken
                })
            });

            if (res.ok) {
                submitted = true;
                setTimeout(() => {
                    submitted = false;
                    isOpen = false;
                }, 2000);
            } else {
                error = "Failed to send. Try again.";
            }
        } catch {
            error = "Network error. Try again.";
        } finally {
            submitting = false;
            if (captchaWidgetId !== null) {
                (window as any).grecaptcha?.reset(captchaWidgetId);
                captchaToken = null;
            }
        }
    }

    function close() {
        isOpen = false;
        error = null;
        captchaWidgetId = null;
        captchaToken = null;
    }
</script>

<!-- FEEDBACK FORM - Comment out  to disable -->
<button class="feedback-toggle" onclick={() => (isOpen = !isOpen)} title="Send Feedback">
    💬
</button>

{#if isOpen}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div class="feedback-overlay" onclick={close}></div>
    <div class="feedback-panel">
        <button class="feedback-close" onclick={close}>✕</button>
        <h3>Send Feedback</h3>

        {#if submitted}
            <p class="feedback-success">Thanks for your feedback!</p>
        {:else}
            <form onsubmit={handleSubmit}>
                <select bind:value={feedbackType}>
                    <option value="feedback">General Feedback</option>
                    <option value="bug">Bug Report</option>
                    <option value="artist">Suggest Artist(s)</option>
                    <option value="album">Suggest Album</option>
                    <option value="track">Suggest Track(s)</option>
                </select>

                {#if feedbackType === "artist"}
                    <p class="field-hint">Add one or more artists:</p>
                    {#each artists as artist, idx}
                        <div class="multi-input">
                            <input
                                type="text"
                                bind:value={artists[idx]}
                                placeholder="Artist name"
                                required={idx === 0 ? true : undefined}
                            />
                            {#if artists.length > 1}
                                <button type="button" class="remove-btn" onclick={() => removeArtist(idx)}>✕</button>
                            {/if}
                        </div>
                    {/each}
                    <button type="button" class="add-btn" onclick={addArtist}>+ Add another artist</button>

                {:else if feedbackType === "album"}
                    <input
                        type="text"
                        bind:value={artistName}
                        placeholder="Artist name *"
                        required
                    />
                    <input
                        type="text"
                        bind:value={albumName}
                        placeholder="Album name *"
                        required
                    />
                    <p class="field-hint">Tracks (optional):</p>
                    {#each tracks as track, idx}
                        <div class="multi-input">
                            <input
                                type="text"
                                bind:value={tracks[idx]}
                                placeholder="Track {idx + 1}"
                            />
                            {#if tracks.length > 1}
                                <button type="button" class="remove-btn" onclick={() => removeTrack(idx)}>✕</button>
                            {/if}
                        </div>
                    {/each}
                    <button type="button" class="add-btn" onclick={addTrack}>+ Add track</button>

                {:else if feedbackType === "track"}
                    <input
                        type="text"
                        bind:value={artistName}
                        placeholder="Artist name *"
                        required
                    />
                    <p class="field-hint">Track(s) to add:</p>
                    {#each tracks as track, idx}
                        <div class="multi-input">
                            <input
                                type="text"
                                bind:value={tracks[idx]}
                                placeholder="Track {idx + 1}"
                                required={idx === 0 ? true : undefined}
                            />
                            {#if tracks.length > 1}
                                <button type="button" class="remove-btn" onclick={() => removeTrack(idx)}>✕</button>
                            {/if}
                        </div>
                    {/each}
                    <button type="button" class="add-btn" onclick={addTrack}>+ Add track</button>
                {/if}

                <textarea
                    bind:value={message}
                    placeholder={feedbackType === "bug"
                        ? "Describe the bug..."
                        : feedbackType === "feedback"
                          ? "Your feedback..."
                          : "Additional notes (optional)..."}
                    rows={feedbackType === "feedback" || feedbackType === "bug" ? 4 : 2}
                    required={feedbackType === "feedback" || feedbackType === "bug"}
                ></textarea>

                <input
                    type="email"
                    bind:value={email}
                    placeholder="Email (optional)"
                />

                <div class="captcha-wrapper" bind:this={captchaContainer}></div>

                {#if error}
                    <p class="feedback-error">{error}</p>
                {/if}

                <button type="submit" disabled={submitting || !isValid()}>
                    {submitting ? "Sending..." : "Send"}
                </button>
            </form>
        {/if}
    </div>
{/if}

<style>
    .feedback-toggle {
        position: fixed;
        bottom: 2rem;
        right: 1rem;
        z-index: 900;
        width: 44px;
        height: 44px;
        border-radius: 50%;
        border: none;
        background: var(--bg-alt);
        font-size: 1.2rem;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        transition: transform 0.15s;
    }

    .feedback-toggle:hover {
        transform: scale(1.1);
    }

    @media (max-width: 768px) {
        .feedback-toggle {
            bottom: 4rem;
        }
    }

    .feedback-overlay {
        position: fixed;
        inset: 0;
        z-index: 1001;
        background: rgba(0, 0, 0, 0.4);
    }

    .feedback-panel {
        position: fixed;
        bottom: 4rem;
        right: 1rem;
        z-index: 1002;
        width: 320px;
        max-width: calc(100vw - 2rem);
        max-height: calc(100vh - 6rem);
        overflow-y: auto;
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }

    .feedback-close {
        position: absolute;
        top: 0.5rem;
        right: 0.5rem;
        background: none;
        border: none;
        font-size: 1rem;
        cursor: pointer;
        color: var(--text-2);
    }

    .feedback-panel h3 {
        margin: 0 0 0.75rem;
        font-size: 1rem;
    }

    .feedback-panel select,
    .feedback-panel textarea,
    .feedback-panel input[type="text"],
    .feedback-panel input[type="email"] {
        width: 100%;
        margin-bottom: 0.5rem;
        padding: 0.5rem 0.65rem;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--bg-alt);
        color: var(--text);
        font-family: inherit;
        font-size: 0.85rem;
        outline: none;
        transition: border-color 0.15s, box-shadow 0.15s;
        box-sizing: border-box;
    }

    /* Fix select dropdown styling */
    .feedback-panel select {
        appearance: none;
        -webkit-appearance: none;
        -moz-appearance: none;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23888' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 0.65rem center;
        padding-right: 2rem;
        cursor: pointer;
    }

    .feedback-panel select option {
        background: var(--bg-alt);
        color: var(--text);
    }

    .feedback-panel select:focus,
    .feedback-panel textarea:focus,
    .feedback-panel input[type="text"]:focus,
    .feedback-panel input[type="email"]:focus {
        border-color: var(--gold);
        box-shadow: 0 0 0 2px var(--gold-glow);
    }

    .feedback-panel textarea {
        resize: vertical;
        min-height: 60px;
    }

    .field-hint {
        font-size: 0.75rem;
        color: var(--text-2);
        margin: 0.25rem 0 0.35rem;
    }

    .multi-input {
        display: flex;
        gap: 0.35rem;
        margin-bottom: 0.35rem;
    }

    .multi-input input {
        flex: 1;
        margin-bottom: 0;
    }

    .remove-btn {
        width: 28px;
        height: 34px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--bg-alt);
        color: var(--text-2);
        cursor: pointer;
        font-size: 0.75rem;
        flex-shrink: 0;
    }

    .remove-btn:hover {
        background: rgba(244, 67, 54, 0.15);
        border-color: #f44336;
        color: #f44336;
    }

    .add-btn {
        width: 100%;
        padding: 0.4rem;
        margin-bottom: 0.5rem;
        border: 1px dashed var(--border);
        border-radius: 6px;
        background: transparent;
        color: var(--text-2);
        font-size: 0.8rem;
        cursor: pointer;
        transition: border-color 0.15s, color 0.15s;
    }

    .add-btn:hover {
        border-color: var(--gold);
        color: var(--gold);
    }

    .feedback-panel button[type="submit"] {
        width: 100%;
        padding: 0.6rem;
        background: var(--gold);
        color: #111;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        transition: filter 0.15s;
    }

    .feedback-panel button[type="submit"]:hover:not(:disabled) {
        filter: brightness(1.1);
    }

    .feedback-panel button[type="submit"]:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .feedback-success {
        color: #4caf50;
        text-align: center;
        padding: 1rem 0;
    }

    .feedback-error {
        color: #f44336;
        font-size: 0.8rem;
        margin-bottom: 0.5rem;
    }

    .captcha-wrapper {
        margin-bottom: 0.5rem;
        transform: scale(0.9);
        transform-origin: left;
    }
</style>
