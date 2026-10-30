<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { registerServiceWorker } from '#lib/sw/register.ts';
	let { children } = $props();

	onMount(() => {
		void registerServiceWorker(navigator, window, import.meta.env.PROD);
	});
</script>

{@render children()}
