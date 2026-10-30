<script lang="ts">
	import { onMount } from 'svelte';
	import Feed from '#lib/components/Feed.svelte';
	import { fetchFeed, postEvents } from '#lib/api.ts';
	import { createBatcher } from '#lib/batcher.ts';
	import type { Card } from '#lib/types.ts';

	let cards = $state<Card[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const batcher = createBatcher(postEvents, 5000);

	onMount(() => {
		batcher.start();
		const onVis = () => {
			if (document.visibilityState === 'hidden') void batcher.flush();
		};
		document.addEventListener('visibilitychange', onVis);
		void load();
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			batcher.stop();
		};
	});

	async function load() {
		try {
			cards = (await fetchFeed()).cards;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}
</script>

<nav class="topbar"><a href="/saved">Saved</a></nav>

{#if error}
	<p class="status error" role="alert">Failed to load feed: {error}</p>
{:else if loading}
	<p class="status">Loading...</p>
{:else if cards.length === 0}
	<p class="status">No cards yet</p>
{:else}
	<Feed {cards} onEvent={(e) => batcher.push(e)} />
{/if}

<style>
	.topbar {
		position: fixed;
		top: 0;
		right: 0;
		z-index: 10;
		padding: 0.5rem 16px;
	}
	.topbar a {
		display: inline-flex;
		align-items: center;
		min-height: 44px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
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
