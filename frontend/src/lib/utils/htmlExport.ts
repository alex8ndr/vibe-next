import type { Track } from "$lib/stores";

export interface ExportOptions {
    recommendations: Record<string, Track[]>;
    selectedArtists: string[];
}

// Helper to escape HTML entities
function escapeHtml(unsafe: string): string {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

export function generateHTML({ recommendations, selectedArtists }: ExportOptions): string {
    // Escape input artists
    const inputArtists = selectedArtists.map(escapeHtml).join(" • ");
    
    const date = new Date().toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
    });

    let cards = "";
    for (const [artist, tracks] of Object.entries(recommendations)) {
        // Safe ID for DOM elements (alphanumeric only)
        const artistId = artist.replace(/[^a-zA-Z0-9]/g, "_");
        // Escape display name
        const displayArtist = escapeHtml(artist);
        const firstTrack = tracks[0]?.track_id || "";

        let trackButtons = "";
        for (let i = 0; i < tracks.length; i++) {
            const track = tracks[i];
            // Escape track name
            const safeName = escapeHtml(track.track_name);
            trackButtons += `<button class="track-btn" onclick="playTrack(this, '${track.track_id}')">${safeName}</button>`;
        }

        cards += `<div class="card" data-artist="${artistId}">
            <h2>${displayArtist}</h2>
            <div class="player-container" id="player_${artistId}" data-track="${firstTrack}"></div>
            <div class="tracks">${trackButtons}</div>
        </div>`;
    }

    return `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="Music recommendations based on ${inputArtists}">
<meta name="generator" content="Vibe">
<title>Vibe Recommendations - ${date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
    --gold: #d4a520;
    --gold-dim: #b8860b;
    --gold-glow: rgba(212, 165, 32, 0.25);
    --bg: #0c0e14;
    --bg-alt: #12151e;
    --surface: #181c28;
    --text: #f0f0f0;
    --text-2: #aaa;
    --text-3: #666;
    --border: #2a2e3a;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { 
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
    background: var(--bg); 
    color: var(--text);
    min-height: 100vh;
    line-height: 1.5;
}
.container {
    max-width: 1200px; 
    margin: 0 auto; 
    padding: 2rem 1.5rem;
}
header {
    text-align: center;
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
}
h1 { 
    font-size: 1.75rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
    letter-spacing: -0.5px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
}
h1 span { color: var(--gold); }
.subtitle {
    color: var(--text-2);
    font-size: 0.9rem;
}
.input-section { 
    background: var(--surface);
    padding: 1rem 1.25rem;
    border-radius: 10px;
    margin-bottom: 2rem;
    border-left: 3px solid var(--gold);
}
.input-label {
    font-size: 0.75rem;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.25rem;
}
.input-artists {
    color: var(--text);
    font-weight: 500;
}
.grid { 
    display: grid; 
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); 
    gap: 1.25rem; 
}
.card { 
    background: var(--surface);
    padding: 1.25rem;
    border-radius: 12px;
    border: 1px solid var(--border);
    transition: border-color 0.2s;
}
.card:hover {
    border-color: var(--gold-dim);
}
.card h2 { 
    color: var(--text); 
    margin: 0 0 1rem 0; 
    font-size: 1.1rem;
    font-weight: 600;
}
.player-container { 
    background: rgba(0,0,0,0.4);
    border-radius: 8px;
    min-height: 80px;
    overflow: hidden;
}
.tracks {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-top: 0.75rem;
}
.track-btn {
    display: block;
    width: 100%;
    padding: 0.6rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-alt);
    color: var(--text);
    text-align: left;
    cursor: pointer;
    font-size: 0.85rem;
    font-family: inherit;
    transition: all 0.15s;
}
.track-btn:hover { 
    border-color: var(--gold);
    color: var(--text);
}
.track-btn.active { 
    background: var(--gold-glow);
    border-color: var(--gold);
    color: var(--gold);
}
footer {
    text-align: center;
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border);
    color: var(--text-3);
    font-size: 0.8rem;
}
footer a {
    color: var(--gold);
    text-decoration: none;
}
footer a:hover {
    text-decoration: underline;
}
.header-icon {
    width: 28px;
    height: 28px;
}
@media (max-width: 768px) {
    .grid {
        grid-template-columns: 1fr;
    }
    .container {
        padding: 1rem;
    }
}
</style>
</head><body>
<div class="container">
    <header>
        <h1>
            <svg class="header-icon" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                <circle cx="50" cy="50" r="48" fill="#2c3e6e" stroke="#1e2a4a" stroke-width="2"/>
                <g fill="#d4af7a" transform="translate(50,50)">
                    <rect x="-4" y="-25" width="8" height="50" rx="4"/>
                    <rect x="-18" y="-18" width="8" height="36" rx="4"/>
                    <rect x="10" y="-18" width="8" height="36" rx="4"/>
                    <rect x="-32" y="-12" width="8" height="24" rx="4"/>
                    <rect x="24" y="-12" width="8" height="24" rx="4"/>
                </g>
            </svg>
            <span>Vibe</span> Recommendations
        </h1>
        <p class="subtitle">Generated on ${date}</p>
    </header>
    <div class="input-section">
        <div class="input-label">Based on</div>
        <div class="input-artists">${inputArtists}</div>
    </div>
    <div class="grid">${cards}</div>
    <footer>
        <p>Created with <a href="https://vibe.alext.dev" target="_blank">Vibe</a></p>
    </footer>
</div>
${"<"}script src="https://open.spotify.com/embed/iframe-api/v1" async>${"<"}/script>
${"<"}script>
const controllers = {};

window.onSpotifyIframeApiReady = (IFrameAPI) => {
    document.querySelectorAll('.player-container').forEach(container => {
        const artistId = container.id.replace('player_', '');
        const trackId = container.dataset.track;
        
        IFrameAPI.createController(container, {
            width: '100%',
            height: '80',
            uri: trackId ? 'spotify:track:' + trackId : ''
        }, (controller) => {
            controllers[artistId] = controller;
        });
    });
};

// State tracking
let currentArtistId = null;
let currentTrackId = null;

function playTrack(btn, trackId) {
    const card = btn.closest('.card');
    const artistId = card.dataset.artist;
    const controller = controllers[artistId];
    
    if (!controller) return;

    // Case 1: Clicked the same track that is already active
    if (currentArtistId === artistId && currentTrackId === trackId) {
        controller.togglePlay();
        return;
    }

    // Case 2: Switching artists - pause the old one
    if (currentArtistId && currentArtistId !== artistId && controllers[currentArtistId]) {
        controllers[currentArtistId].pause();
    }
    
    // Case 3: Play new track
    controller.loadUri('spotify:track:' + trackId);
    controller.play();
    
    // Update state
    currentArtistId = artistId;
    currentTrackId = trackId;
    
    // Update UI highlights
    document.querySelectorAll('.track-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    
    // Also update this card's other buttons to ensure only one is active
    card.querySelectorAll('.track-btn').forEach(b => {
        if (b !== btn) b.classList.remove('active');
    });
}
${"<"}/script>
</body></html>`;
}
