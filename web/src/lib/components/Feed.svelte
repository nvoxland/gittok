<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import CardView from './Card.svelte';
	import type { Card, FeedEvent } from '#lib/types.ts';
	import { getSessionId } from '#lib/session.ts';
	import { playStats } from '#lib/playStats.ts';
	import { scrollBehavior } from '#lib/motion.ts';

	let {
		cards,
		onEvent,
		onNearEnd,
		onActive
	}: {
		cards: Card[];
		onEvent?: (e: FeedEvent) => void;
		onNearEnd?: () => void;
		onActive?: (id: string) => void;
	} = $props();

	// Ask for the next page while this many cards are still ahead, so the feed never runs out.
	const NEAR_END = 5;
	// Full cards are mounted only this many places before and after the card on screen. Every
	// other card is an empty placeholder of the same height, so a long session does not keep
	// hundreds of cards (code blocks, diagrams, images) alive. The scroll height, the snap points
	// and the watched elements stay the same.
	const WINDOW = 3;

	let root: HTMLElement | undefined = $state();
	const visibleSince = new Map<string, number>();
	const seen = new Set<string>();
	// Cards at least 60% visible, whether or not the tab is shown. visibleSince only holds
	// the ones whose dwell timer is running.
	const inView = new Set<string>();

	function emit(card_id: string, type: FeedEvent['type'], data?: Record<string, unknown>) {
		onEvent?.({ card_id, type, ts: Date.now(), data: { ...data, session: getSessionId() } });
	}

	// The card that plays its beats: on screen and the tab shown.
	let activeId = $state<string | null>(null);
	let pageShown = $state(true);
	// The last card that was on screen: the window stays around it while two cards share the screen.
	let anchorId = $state<string | null>(null);
	const anchor = $derived.by(() => {
		const i = anchorId === null ? -1 : cards.findIndex((c) => c.id === anchorId);
		return i < 0 ? 0 : i;
	});

	function closeDwell(id: string) {
		const since = visibleSince.get(id);
		if (since === undefined) return;
		const ms = Date.now() - since;
		visibleSince.delete(id);
		// A beat card reports watch time like a video; leaving during its first beat is a skip.
		const play = playStats(id);
		if (play && play.totalMs > 0) {
			emit(id, 'dwell', { ms, ms_played: play.msPlayed, total_ms: play.totalMs });
			if (!play.done && play.beat <= 0) emit(id, 'skip');
			return;
		}
		emit(id, 'dwell', { ms });
		if (ms < 1000) emit(id, 'skip');
	}

	function onVisibility() {
		pageShown = document.visibilityState !== 'hidden';
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
			if (visible) {
				activeId = id;
				anchorId = id;
				onActive?.(id);
				if (cards.findIndex((c) => c.id === id) >= cards.length - 1 - NEAR_END) onNearEnd?.();
			}
			else if (activeId === id) activeId = null;
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

	// One observer for the life of the feed. A card and its placeholder are different elements,
	// so after each change of the list or the window: watch the new elements, drop the gone ones.
	// A card that swaps while on screen is reported once more as visible; its dwell timer is
	// already running, so that is not a second impression.
	let io: IntersectionObserver | undefined;
	const watched = new Set<Element>();

	$effect(() => {
		void cards;
		void anchor;
		if (!root || typeof IntersectionObserver === 'undefined') return;
		io ??= new IntersectionObserver(onIntersect, { threshold: 0.6 });
		const now = new Set(root.querySelectorAll('[data-card-id]'));
		for (const el of watched) {
			if (now.has(el)) continue;
			io.unobserve(el);
			watched.delete(el);
		}
		for (const el of now) {
			if (watched.has(el)) continue;
			io.observe(el);
			watched.add(el);
		}
	});

	onDestroy(() => io?.disconnect());

	// Keyboard: j or ArrowDown is the next card, k or ArrowUp the previous one. A card may use the
	// arrow keys first (a long depth panel scrolls); it then marks the event as handled.
	function onKey(e: KeyboardEvent) {
		if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
		const dir =
			e.key === 'j' || e.key === 'ArrowDown' ? 1 : e.key === 'k' || e.key === 'ArrowUp' ? -1 : 0;
		if (!dir || !root) return;
		if ((e.target as Element | null)?.closest?.('input, textarea, select, [contenteditable]')) return;
		if (document.querySelector('[aria-modal="true"]')) return; // lightbox or story viewer
		const els = root.querySelectorAll<HTMLElement>('[data-card-id]');
		let next = anchor + dir;
		// Below the last card (on the end card): "up" is that last card, not the one before it.
		if (activeId === null && dir < 0 && els[anchor]?.getBoundingClientRect().bottom <= 1) next = anchor;
		const el = els[next];
		if (!el) return; // past either end: the browser scrolls (the top bar, the end card)
		e.preventDefault();
		// The first card snaps by its bottom edge, under the top bar.
		el.scrollIntoView?.({ behavior: scrollBehavior(), block: next === 0 ? 'end' : 'start' });
	}
</script>

<svelte:window onkeydown={onKey} />

<div class="feed" bind:this={root}>
	{#each cards as card, i (card.id)}
		{#if Math.abs(i - anchor) <= WINDOW}
			<CardView
				{card}
				first={i === 0}
				active={activeId === card.id && pageShown}
				onPanelChange={(panel) => emit(card.id, 'depth_open', { panel })}
				onAction={(type, data) => emit(card.id, type, data)}
			/>
		{:else}
			<article
				class="placeholder"
				class:first={i === 0}
				data-card-id={card.id}
				aria-label={card.hook}
			></article>
		{/if}
	{/each}
</div>

<style>
	/* The page itself scrolls (not this box), so mobile browsers collapse their toolbars. */
	:global(html) {
		scroll-snap-type: y mandatory;
	}
	/* Same box as a card (Card.svelte: article), so the page height and the snap points never move. */
	.placeholder {
		height: 100dvh;
		scroll-snap-align: start;
	}
	.placeholder.first {
		height: calc(100dvh - var(--chrome-h, 0px));
		scroll-snap-align: end;
	}
</style>
