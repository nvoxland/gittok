<script lang="ts">
	import type { Card } from '#lib/types.ts';

	let { card }: { card: Card } = $props();
</script>

<article data-card-id={card.id}>
	<h2>{card.hook}</h2>
</article>

<style>
	article {
		height: 100dvh;
		scroll-snap-align: start;
		display: grid;
		place-items: center;
		padding: 1rem;
	}
	h2 {
		margin: 0;
		font-size: 1.5rem;
	}
</style>
