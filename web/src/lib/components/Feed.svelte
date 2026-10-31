<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import CardView from './Card.svelte';
	import type { Card, FeedEvent } from '#lib/types.ts';
	import { getSessionId } from '#lib/session.ts';

	let { cards, onEvent }: { cards: Card[]; onEvent?: (e: FeedEvent) => void } = $props();

	let root: HTMLElement | undefined = $state();
	const visibleSince = new Map<string, number>();
	const seen = new Set<string>();
	// Cards at least 60% visible, whether or not the tab is shown. visibleSince only holds
	// the ones whose dwell timer is running.
	const inView = new Set<string>();

	function emit(card_id: string, type: FeedEvent['type'], data?: Record<string, unknown>) {
		onEvent?.({ card_id, type, ts: Date.now(), data: { ...data, session: getSessionId() } });
	}

	function closeDwell(id: string) {
		const since = visibleSince.get(id);
		if (since === undefined) return;
		const ms = Date.now() - since;
		visibleSince.delete(id);
		emit(id, 'dwell', { ms });
		if (ms < 1000) emit(id, 'skip');
	}

	function onVisibility() {
		if (document.visibilityState === 'hidden') {
			for (const id of [...visibleSince.keys()]) closeDwell(id);
		} else {
			// Back on screen: restart the timer, but this is not a new impression.
			for (const id of inView) if (!visibleSince.has(id)) visibleSince.set(id, Date.now());
		}
	}

	onMount(() => {
		document.addEventListener('visibilitychange', onVisibility);
		return () => document.removeEventListener('visibilitychange', onVisibility);
	});

	onDestroy(() => {
		for (const id of [...visibleSince.keys()]) closeDwell(id);
	});

	function onIntersect(entries: IntersectionObserverEntry[]) {
		for (const entry of entries) {
			const id = (entry.target as HTMLElement).dataset.cardId;
			if (!id) continue;
			const visible = entry.isIntersecting && entry.intersectionRatio >= 0.6;
			if (visible) inView.add(id);
			else inView.delete(id);
			if (document.visibilityState === 'hidden') continue; // timers restart when shown
			if (visible && !visibleSince.has(id)) {
				visibleSince.set(id, Date.now());
				emit(id, 'impression');
				if (seen.has(id)) emit(id, 'scroll_back');
				seen.add(id);
			} else if (!visible) {
				closeDwell(id);
			}
		}
	}

	$effect(() => {
		void cards;
		if (!root || typeof IntersectionObserver === 'undefined') return;
		const io = new IntersectionObserver(onIntersect, { threshold: 0.6 });
		root.querySelectorAll('[data-card-id]').forEach((el) => io.observe(el));
		return () => io.disconnect();
	});
</script>

<div class="feed" bind:this={root}>
	{#each cards as card, i (card.id)}
		<CardView
			{card}
			first={i === 0}
			onPanelChange={(panel) => emit(card.id, 'depth_open', { panel })}
			onAction={(type, data) => emit(card.id, type, data)}
		/>
	{/each}
</div>

<style>
	/* The page itself scrolls (not this box), so mobile browsers collapse their toolbars. */
	:global(html) {
		scroll-snap-type: y mandatory;
	}
</style>
