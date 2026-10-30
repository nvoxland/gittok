<script lang="ts">
	import CardView from './Card.svelte';
	import type { Card, FeedEvent } from '#lib/types.ts';
	import { getSessionId } from '#lib/session.ts';

	let { cards, onEvent }: { cards: Card[]; onEvent?: (e: FeedEvent) => void } = $props();

	let root: HTMLElement | undefined = $state();
	const visibleSince = new Map<string, number>();
	const seen = new Set<string>();

	function emit(card_id: string, type: FeedEvent['type'], data?: Record<string, unknown>) {
		onEvent?.({ card_id, type, ts: Date.now(), data: { ...data, session: getSessionId() } });
	}

	function onIntersect(entries: IntersectionObserverEntry[]) {
		for (const entry of entries) {
			const id = (entry.target as HTMLElement).dataset.cardId;
			if (!id) continue;
			const visible = entry.isIntersecting && entry.intersectionRatio >= 0.6;
			if (visible && !visibleSince.has(id)) {
				visibleSince.set(id, Date.now());
				emit(id, 'impression');
				if (seen.has(id)) emit(id, 'scroll_back');
				seen.add(id);
			} else if (!visible && visibleSince.has(id)) {
				const ms = Date.now() - visibleSince.get(id)!;
				visibleSince.delete(id);
				emit(id, 'dwell', { ms });
				if (ms < 1000) emit(id, 'skip');
			}
		}
	}

	$effect(() => {
		void cards;
		if (!root || typeof IntersectionObserver === 'undefined') return;
		const io = new IntersectionObserver(onIntersect, { root, threshold: 0.6 });
		root.querySelectorAll('[data-card-id]').forEach((el) => io.observe(el));
		return () => io.disconnect();
	});
</script>

<div class="feed" bind:this={root}>
	{#each cards as card (card.id)}
		<CardView
			{card}
			onPanelChange={(panel) => emit(card.id, 'depth_open', { panel })}
			onAction={(type, data) => emit(card.id, type, data)}
		/>
	{/each}
</div>

<style>
	.feed {
		height: 100dvh;
		overflow-y: auto;
		scroll-snap-type: y mandatory;
	}
</style>
