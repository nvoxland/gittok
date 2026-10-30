<script lang="ts">
	import CardView from './Card.svelte';
	import type { Card } from '#lib/types.ts';

	let { cards }: { cards: Card[] } = $props();
</script>

<div class="feed">
	{#each cards as card (card.id)}
		<CardView {card} />
	{/each}
</div>

<style>
	.feed {
		height: 100dvh;
		overflow-y: auto;
		scroll-snap-type: y mandatory;
	}
</style>
