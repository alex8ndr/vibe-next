<script lang="ts">
	import "../app.css";
	import { hasResults } from "$lib/stores";

	let { children } = $props();
	let settingsOpen = $state(false);
</script>

<svelte:head>
	<title>Vibe</title>
	<meta
		name="description"
		content="Discover music based on artists you love"
	/>
	<link rel="preconnect" href="https://open.spotify.com" />
	<link rel="preconnect" href="https://i.scdn.co" />
</svelte:head>

<div class="app" class:has-results={$hasResults}>
	<header class="header">
		<a href="https://alext.dev" class="author">alext.dev</a>

		<div class="brand">
			<svg class="logo" viewBox="0 0 40 40" fill="none">
				<circle
					cx="20"
					cy="20"
					r="18"
					stroke="currentColor"
					stroke-width="2"
				/>
				<path
					d="M14 14v12M20 10v20M26 14v12"
					stroke="currentColor"
					stroke-width="2.5"
					stroke-linecap="round"
				/>
			</svg>
			<span class="name">Vibe</span>
		</div>

		<button
			class="settings-btn"
			onclick={() => (settingsOpen = !settingsOpen)}
			aria-label="Settings"
		>
			<svg
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
			>
				<circle cx="12" cy="12" r="3" />
				<path
					d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"
				/>
			</svg>
		</button>

		{#if settingsOpen}
			<div class="settings-dropdown">
				<h4>Settings</h4>
				<label class="setting">
					<span>Variety</span>
					<select>
						<option>Low</option>
						<option selected>Medium</option>
						<option>High</option>
					</select>
				</label>
				<label class="setting">
					<span>Genre Weight</span>
					<input type="range" min="0" max="5" step="0.5" value="2" />
				</label>
				<label class="setting">
					<span>Max Results</span>
					<input type="number" min="3" max="12" value="6" />
				</label>
			</div>
		{/if}
	</header>

	<main class="main">
		{@render children()}
	</main>
</div>

<style>
	.app {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}

	.header {
		position: sticky;
		top: 0;
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem 1.5rem;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
	}

	.author {
		font-size: 0.85rem;
		font-weight: 500;
		color: var(--text-2);
	}

	.author:hover {
		color: var(--gold);
	}

	.brand {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.logo {
		width: 28px;
		height: 28px;
		color: var(--gold);
	}

	.name {
		font-size: 1.25rem;
		font-weight: 700;
		letter-spacing: -0.5px;
		color: var(--text);
	}

	.settings-btn {
		width: 32px;
		height: 32px;
		padding: 6px;
		background: none;
		border: none;
		color: var(--text-3);
		border-radius: 6px;
		transition:
			color 0.15s,
			background 0.15s;
	}

	.settings-btn:hover {
		color: var(--text);
		background: var(--bg-alt);
	}

	.settings-btn svg {
		width: 100%;
		height: 100%;
	}

	.settings-dropdown {
		position: absolute;
		top: 100%;
		right: 1rem;
		width: 240px;
		padding: 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		box-shadow: 0 8px 24px var(--shadow);
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.settings-dropdown h4 {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text-3);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		margin-bottom: 0.25rem;
	}

	.setting {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.875rem;
		color: var(--text-2);
	}

	.setting select,
	.setting input[type="number"] {
		padding: 0.3rem 0.5rem;
		background: var(--bg-alt);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.8rem;
	}

	.setting input[type="range"] {
		width: 80px;
		accent-color: var(--gold);
	}

	.main {
		flex: 1;
		display: flex;
		flex-direction: column;
	}

	@media (max-width: 640px) {
		.header {
			padding: 0.5rem 1rem;
		}

		.author {
			font-size: 0.75rem;
		}

		.name {
			display: none;
		}

		.settings-dropdown {
			left: 1rem;
			right: 1rem;
			width: auto;
		}
	}
</style>
