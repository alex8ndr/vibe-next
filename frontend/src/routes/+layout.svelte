<script lang="ts">
	import "../app.css";
	import {
		hasResults,
		settings,
		themePreference,
		recommendations,
	} from "$lib/stores";
	import { onMount } from "svelte";

	const DEV_MODE = import.meta.env.DEV;

	let { children } = $props();
	let settingsOpen = $state(false);
	let settingsDropdown = $state<HTMLDivElement | null>(null);
	let mounted = $state(false);

	onMount(() => {
		mounted = true;
		applyTheme($themePreference);
		syncBackgroundAttr($settings.showBackground);
	});

	function applyTheme(pref: "light" | "dark" | "system") {
		if (typeof document === "undefined") return;

		if (pref === "system") {
			document.documentElement.removeAttribute("data-theme");
		} else {
			document.documentElement.setAttribute("data-theme", pref);
		}
	}

	function syncBackgroundAttr(show: boolean) {
		if (typeof document === "undefined") return;
		if (show) {
			document.documentElement.removeAttribute("data-no-bg");
		} else {
			document.documentElement.setAttribute("data-no-bg", "");
		}
	}

	$effect(() => {
		if (mounted) applyTheme($themePreference);
	});

	$effect(() => {
		if (mounted) syncBackgroundAttr($settings.showBackground);
	});

	function getActualTheme(): "light" | "dark" {
		if (typeof window === "undefined") return "dark";
		return window.matchMedia("(prefers-color-scheme: dark)").matches
			? "dark"
			: "light";
	}

	function cycleTheme() {
		if ($themePreference === "system") {
			// Switch to opposite of current actual appearance
			const actual = getActualTheme();
			themePreference.set(actual === "dark" ? "light" : "dark");
		} else if ($themePreference === "light") {
			themePreference.set("dark");
		} else {
			themePreference.set("system");
		}
	}

	function handleOutsideClick(e: MouseEvent) {
		if (
			settingsOpen &&
			settingsDropdown &&
			!settingsDropdown.contains(e.target as Node)
		) {
			const btn = (e.target as HTMLElement).closest(
				'.icon-btn[aria-label="Settings"]',
			);
			if (!btn) settingsOpen = false;
		}
	}

	const themeIcon = $derived(
		$themePreference === "light"
			? "☀️"
			: $themePreference === "dark"
				? "🌙"
				: "⚙️",
	);
</script>

<svelte:window on:click={handleOutsideClick} />

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
		<a
			href="https://alext.dev"
			class="author"
			target="_blank"
			rel="noopener">alext.dev</a
		>

		<a
			href="/"
			class="brand"
			onclick={(e) => {
				e.preventDefault();
				recommendations.set({});
			}}
		>
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
		</a>

		<div class="header-actions">
			<button
				class="icon-btn"
				onclick={cycleTheme}
				title="Theme: {$themePreference}"
			>
				{themeIcon}
			</button>

			<button
				class="icon-btn"
				onclick={() => (settingsOpen = !settingsOpen)}
				aria-label="Settings"
			>
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<path d="M12 15a3 3 0 100-6 3 3 0 000 6z" />
					<path
						d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"
					/>
				</svg>
			</button>

			{#if settingsOpen}
				<div class="dropdown" bind:this={settingsDropdown}>
					<h4>Settings</h4>

					{#if DEV_MODE}
						<label class="setting dev">
							<span>Show Background</span>
							<input
								type="checkbox"
								checked={$settings.showBackground}
								onchange={() =>
									settings.update((s) => ({
										...s,
										showBackground: !s.showBackground,
									}))}
							/>
						</label>
					{:else}
						<p class="empty-msg">No global settings</p>
					{/if}
				</div>
			{/if}
		</div>
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
		padding: 0.6rem 1.25rem;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
	}

	.author {
		font-size: 0.8rem;
		font-weight: 500;
		color: var(--text-2);
		text-decoration: none;
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
		gap: 0.4rem;
		text-decoration: none;
		color: inherit;
	}

	.brand:hover {
		text-decoration: none;
	}

	.logo {
		width: 26px;
		height: 26px;
		color: var(--gold);
	}

	.name {
		font-size: 1.15rem;
		font-weight: 700;
		letter-spacing: -0.5px;
		color: var(--text);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		position: relative;
	}

	.icon-btn {
		width: 32px;
		height: 32px;
		padding: 5px;
		background: none;
		border: none;
		color: var(--text-3);
		border-radius: 6px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 1rem;
	}

	.icon-btn:hover {
		color: var(--text);
		background: var(--bg-alt);
	}

	.icon-btn svg {
		width: 18px;
		height: 18px;
	}

	.dropdown {
		position: absolute;
		top: 100%;
		right: 0;
		margin-top: 0.5rem;
		width: 220px;
		padding: 0.75rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		box-shadow: 0 8px 24px var(--shadow);
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.dropdown h4 {
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--text-3);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		margin-bottom: 0.2rem;
	}

	.setting {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		font-size: 0.8rem;
		color: var(--text-2);
	}

	.setting.dev {
		color: #e55;
	}

	.setting input[type="checkbox"] {
		accent-color: var(--gold);
	}

	.empty-msg {
		font-size: 0.75rem;
		color: var(--text-3);
		font-style: italic;
		text-align: center;
		padding: 0.5rem 0;
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

		.name {
			display: none;
		}

		.dropdown {
			position: fixed;
			left: 1rem;
			right: 1rem;
			width: auto;
		}
	}
</style>
