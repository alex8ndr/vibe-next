<script lang="ts">
	import "../app.css";
	import {
		hasResults,
		settings,
		themePreference,
		recommendations,
	} from "$lib/stores";
	import { goto } from "$app/navigation";
	import { onMount } from "svelte";
	import { page } from "$app/state";

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

	function setTheme(pref: "light" | "dark" | "system") {
		themePreference.set(pref);
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
		<div class="author-links">
			<a
				href="https://alext.dev"
				class="author"
				target="_blank"
				rel="noopener">alext.dev</a
			>
			<a
				href="https://ko-fi.com/alextdev"
				class="author author-kofi"
				target="_blank"
				rel="noopener"
				aria-label="Support on Ko-fi"
				title="Support on Ko-fi"
			>
				<svg viewBox="0 0 24 24" fill="currentColor" fill-opacity="0.75">
					<path d="M23.881 8.948c-.773-4.085-4.859-4.593-4.859-4.593H.723c-.604 0-.679.798-.679.798s-.082 7.324-.022 11.822c.164 2.424 2.586 2.672 2.586 2.672s8.267-.023 11.966-.049c2.438-.426 2.683-2.566 2.658-3.734 4.352.24 7.422-2.831 6.649-6.916zm-11.062 3.511c-1.246 1.453-4.011 3.976-4.011 3.976s-.121.119-.31.023c-.076-.057-.108-.09-.108-.09-.443-.441-3.368-3.049-4.034-3.954-.709-.965-1.041-2.7-.091-3.71.951-1.01 3.005-1.086 4.363.407 0 0 1.565-1.782 3.468-.963 1.904.82 1.832 3.011.723 4.311zm6.173.478c-.928.116-1.682.028-1.682.028V7.284h1.77s1.971.551 1.971 2.638c0 1.913-.985 2.667-2.059 3.015z"/>
				</svg>
			</a>
		</div>

		<a
			href="/"
			class="brand"
			onclick={(e) => {
				e.preventDefault();
				recommendations.set({});
				// Navigate to home if not already there (handles 404 pages)
				if (page.url.pathname !== "/") {
					goto("/");
				}
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
			<div class="theme-toggle" title="Theme">
				<button
					class="theme-btn"
					class:active={$themePreference === "light"}
					onclick={() => setTheme("light")}
					aria-label="Light theme"
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="12" cy="12" r="5"/>
						<path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
					</svg>
				</button>
				<button
					class="theme-btn"
					class:active={$themePreference === "system"}
					onclick={() => setTheme("system")}
					aria-label="System theme"
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
						<path d="M8 21h8M12 17v4"/>
					</svg>
				</button>
				<button
					class="theme-btn"
					class:active={$themePreference === "dark"}
					onclick={() => setTheme("dark")}
					aria-label="Dark theme"
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
					</svg>
				</button>
			</div>

			<!-- Settings button hidden for now
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
			-->
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

	.author-links {
		display: flex;
		align-items: center;
		gap: 0.45rem;
	}

	.author:hover {
		color: var(--gold);
	}

	.author-kofi {
		display: inline-flex;
		display: none;
		align-items: center;
		justify-content: center;
	}

	.author-kofi svg {
		width: 1.4rem;
		height: 1.4rem;
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

	/* Theme toggle segmented control */
	.theme-toggle {
		display: flex;
		background: var(--bg-alt);
		border-radius: 6px;
		padding: 2px;
		gap: 2px;
	}

	.theme-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 24px;
		padding: 3px;
		background: transparent;
		border: none;
		border-radius: 4px;
		color: var(--text-3);
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.theme-btn:hover {
		color: var(--text);
		background: var(--surface);
	}

	.theme-btn.active {
		background: var(--surface);
		color: var(--gold);
		box-shadow: 0 1px 2px var(--shadow);
	}

	.theme-btn svg {
		width: 14px;
		height: 14px;
	}

	/* 
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
	*/

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

		/* 
		.dropdown {
			position: fixed;
			left: 1rem;
			right: 1rem;
			width: auto;
		}
		*/
	}
</style>
