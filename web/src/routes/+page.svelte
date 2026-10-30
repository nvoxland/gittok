<script lang="ts">
	import { onMount } from 'svelte';
	import Feed from '$lib/components/Feed.svelte';
	import { fetchFeed } from '$lib/api';
	import type { Card } from '$lib/types';

	let cards = $state<Card[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	onMount(async () => {
		try {
			cards = (await fetchFeed()).cards;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});
</script>

{#if error}
	<p class="status error" role="alert">Failed to load feed: {error}</p>
{:else if loading}
	<p class="status">Loading...</p>
{:else if cards.length === 0}
	<p class="status">No cards yet</p>
{:else}
	<Feed {cards} />
{/if}

<style>
	.status {
		display: grid;
		place-items: center;
		height: 100dvh;
		margin: 0;
		color: var(--muted);
	}
	.error {
		color: #e5484d;
	}
</style>
