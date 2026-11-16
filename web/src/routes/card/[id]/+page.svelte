<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '#lib/components/Card.svelte';
	import { postEvents } from '#lib/api.ts';
	import { createBatcher } from '#lib/batcher.ts';
	import { getSessionId } from '#lib/session.ts';
	let { data } = $props();

	// Like, save and dislike reach the server like in the feed; the rest is flushed on exit.
	const batcher = createBatcher(postEvents, 5000);
	onMount(() => {
		batcher.start();
		const onVis = () => {
			if (document.visibilityState === 'hidden') batcher.flushOnExit();
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			batcher.stop();
		};
	});
</script>

<a class="back" href="/">&larr; Feed</a>
<!-- A new card id gets a fresh Card: it reads its saved state and answer only once. -->
{#key data.card.id}
	<Card
		card={data.card}
		onAction={(type, extra) =>
			batcher.push({
				card_id: data.card.id,
				type,
				ts: Date.now(),
				data: { ...extra, session: getSessionId() }
			})}
	/>
{/key}

<style>
	.back {
		display: block;
		padding: calc(0.5rem + var(--safe-top)) max(16px, var(--safe-right)) 0 max(16px, var(--safe-left));
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
</style>
