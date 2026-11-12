<script lang="ts">
	// Full-screen viewer for a card's visual at natural size. It lives on
	// document.body, outside the feed's snap scroller, and scrolls on its own.
	import { onMount, type Component } from 'svelte';
	import { isDismissSwipe } from '#lib/lightbox.ts';
	import { setEagerImages } from '#lib/imageLoading.ts';
	import type { Card } from '#lib/types.ts';

	let {
		card,
		Visual,
		onClose
	}: {
		card: Card;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		Visual: Component<any>;
		onClose: () => void;
	} = $props();

	// The lightbox is on screen as soon as it opens.
	setEagerImages(() => true);

	let dialog: HTMLElement | undefined = $state();
	let body: HTMLElement | undefined = $state();
	let closeBtn: HTMLButtonElement | undefined = $state();

	const imageKind = $derived(['meme', 'illustration', 'comic'].includes(card.visual.kind));

	// Move the dialog to <body> so no card ancestor can clip or transform it.
	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}

	onMount(() => {
		const before = document.activeElement as HTMLElement | null;
		const overflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		closeBtn?.focus();
		return () => {
			document.body.style.overflow = overflow;
			before?.focus?.();
		};
	});

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.stopPropagation();
			onClose();
			return;
		}
		if (e.key !== 'Tab' || !dialog) return;
		const items = [
			...dialog.querySelectorAll<HTMLElement>('button, a[href], input, textarea, [tabindex="0"]')
		].filter((el) => !el.hasAttribute('disabled'));
		if (!items.length) return;
		const first = items[0];
		const last = items[items.length - 1];
		const at = document.activeElement;
		if (e.shiftKey && (at === first || !dialog.contains(at))) {
			e.preventDefault();
			last.focus();
		} else if (!e.shiftKey && (at === last || !dialog.contains(at))) {
			e.preventDefault();
			first.focus();
		}
	}

	let start: { x: number; y: number } | null = null;
	function touchStart(e: TouchEvent) {
		const t = e.touches[0];
		start = t && e.touches.length === 1 ? { x: t.clientX, y: t.clientY } : null;
	}
	function touchEnd(e: TouchEvent) {
		const t = e.changedTouches[0];
		if (start && t && isDismissSwipe(t.clientX - start.x, t.clientY - start.y, body?.scrollTop ?? 0)) {
			onClose();
		}
		start = null;
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
	class="lightbox"
	role="dialog"
	aria-modal="true"
	aria-label="Expanded {card.visual.kind}"
	tabindex="-1"
	use:portal
	bind:this={dialog}
	onkeydown={onKey}
>
	<header>
		<p class="caption">{card.hook}</p>
		<button type="button" class="close" aria-label="Close" bind:this={closeBtn} onclick={onClose}
			>✕</button
		>
	</header>
	<div
		class="lb-body"
		class:media-kind={imageKind}
		bind:this={body}
		ontouchstart={touchStart}
		ontouchend={touchEnd}
	>
		<Visual
			visual={card.visual}
			resolved={card.resolved.visual}
			persona={card.persona}
			shown={Infinity}
			full
		/>
	</div>
</div>

<style>
	.lightbox {
		position: fixed;
		inset: 0;
		z-index: 1000;
		display: flex;
		flex-direction: column;
		background: color-mix(in srgb, #000 88%, var(--bg, #000));
		color: var(--text, #fff);
		overscroll-behavior: contain;
	}
	header {
		flex: none;
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		padding: calc(0.75rem + env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) 0.5rem
			max(16px, env(safe-area-inset-left));
	}
	.caption {
		flex: 1;
		margin: 0;
		font-weight: 600;
		color: #fff;
	}
	.close {
		flex: none;
		width: 44px;
		height: 44px;
		border: 0;
		border-radius: 50%;
		background: rgb(255 255 255 / 0.15);
		color: #fff;
		font-size: 1.1rem;
		cursor: pointer;
	}
	.lb-body {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding: 0 max(16px, env(safe-area-inset-right)) calc(24px + env(safe-area-inset-bottom))
			max(16px, env(safe-area-inset-left));
		overscroll-behavior: contain;
		-webkit-overflow-scrolling: touch;
		/* The content sits on a card-like surface so themed visuals stay readable on the dark backdrop. */
		color: var(--text);
	}
	.lb-body > :global(*) {
		background: var(--bg);
		border-radius: 8px;
		padding: 0.5rem;
		box-sizing: border-box;
	}
	/* Images: full width, pinch to zoom. */
	.lb-body.media-kind {
		touch-action: pinch-zoom pan-x pan-y;
	}
	.lb-body.media-kind > :global(*) {
		padding: 0;
		background: none;
	}
	/* Not avatars: a group chat's sender icons stay small. */
	.lb-body :global(img:not(.avatar)) {
		max-height: none !important;
		width: 100%;
		height: auto;
	}
</style>
