<script lang="ts">
	import "../app.css";

	let { children } = $props();
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

{@render children()}
