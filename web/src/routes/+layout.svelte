<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { registerServiceWorker } from '#lib/sw/register.ts';
	let { children } = $props();

	onMount(() => {
		void registerServiceWorker(navigator, window, import.meta.env.PROD);
	});
</script>

<!-- Opaque bands over the safe areas in the home-screen app: see .edge in app.css. -->
<div class="edge top" aria-hidden="true"></div>
<div class="edge bottom" aria-hidden="true"></div>
{@render children()}
