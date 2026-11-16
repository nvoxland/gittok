<script lang="ts">
	import { onMount } from 'svelte';
	import { relativeTime } from '#lib/relativeTime.ts';
	import type { Story, StoryCommit } from '#lib/types.ts';

	let {
		story,
		onClose,
		onSeen,
		now = Date.now() / 1000
	}: {
		story: Story;
		onClose: () => void;
		onSeen?: (repo: string, shas: string[]) => void;
		now?: number;
	} = $props();

	// The digest card, when there is one, is the first page.
	type Page = { digest: NonNullable<Story['digest']> } | { commit: StoryCommit };
	const pages: Page[] = $derived([
		...(story.digest ? [{ digest: story.digest }] : []),
		...story.commits.map((c) => ({ commit: c }))
	]);

	let index = $state(0);
	const shown = new Set<string>();
	const page = $derived(pages[index]);
	const commit = $derived(page && 'commit' in page ? page.commit : undefined);

	$effect(() => {
		const sha = commit?.sha;
		if (sha && !shown.has(sha)) {
			shown.add(sha);
			onSeen?.(story.repo, [sha]);
		}
	});

	function next() {
		if (index >= pages.length - 1) onClose();
		else index += 1;
	}

	function prev() {
		if (index > 0) index -= 1;
	}

	let startY = 0;
	function onTouchStart(e: TouchEvent) {
		startY = e.touches[0]?.clientY ?? 0;
	}
	function onTouchEnd(e: TouchEvent) {
		const endY = e.changedTouches[0]?.clientY ?? startY;
		if (endY - startY > 80) onClose();
	}
	let dialog: HTMLElement | undefined = $state();
	let closeBtn: HTMLButtonElement | undefined = $state();

	// Like the Lightbox: focus moves in, the page behind does not scroll, and both are undone on close.
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

	function trapTab(e: KeyboardEvent) {
		if (!dialog) return;
		const items = [...dialog.querySelectorAll<HTMLElement>('button, a[href]')].filter(
			(el) => !el.hasAttribute('disabled')
		);
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

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
		else if (e.key === 'ArrowRight') next();
		else if (e.key === 'ArrowLeft') prev();
		else if (e.key === 'Tab') trapTab(e);
	}
</script>

<svelte:window onkeydown={onKey} />

<div
	class="viewer"
	role="dialog"
	aria-modal="true"
	aria-label="{story.repo} story"
	tabindex="-1"
	bind:this={dialog}
	ontouchstart={onTouchStart}
	ontouchend={onTouchEnd}
>
	<div class="bars">
		{#each pages as p, i ('commit' in p ? p.commit.sha : 'digest')}
			<span
				class="bar"
				data-testid="progress"
				data-state={i < index ? 'done' : i === index ? 'active' : 'upcoming'}
			></span>
		{/each}
	</div>
	<div class="head">
		<strong>{story.repo}</strong>
		<button type="button" class="close" aria-label="Close" bind:this={closeBtn} onclick={onClose}>&#10005;</button>
	</div>
	{#if page && 'digest' in page}
		<div class="page">
			<p class="meta">Daily digest · {page.digest.day}</p>
			<p class="subject">{page.digest.hook}</p>
			<p class="meta">{page.digest.learn}</p>
			<a class="link" href="/card/{page.digest.card_id}">Read card</a>
		</div>
	{:else if commit}
		<div class="page">
			<p class="subject">{commit.subject}</p>
			<p class="meta">{commit.author} · {relativeTime(commit.ts, now)}</p>
			<p class="meta">{commit.files} {commit.files === 1 ? 'file' : 'files'}</p>
			<code class="sha">{commit.short}</code>
			{#if commit.card_id}
				<a class="link" href="/card/{commit.card_id}">Read the card</a>
			{:else if commit.url}
				<a class="link" href={commit.url} target="_blank" rel="noopener noreferrer"
					>View commit on GitHub</a
				>
			{/if}
		</div>
	{/if}
	<button type="button" class="zone left" aria-label="Previous" onclick={prev}></button>
	<button type="button" class="zone right" aria-label="Next" onclick={next}></button>
</div>

<style>
	.viewer {
		position: fixed;
		inset: 0;
		z-index: 100;
		overscroll-behavior: contain;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		color: var(--text);
		padding: env(safe-area-inset-top) 16px env(safe-area-inset-bottom);
	}
	.bars {
		display: flex;
		gap: 4px;
		padding-top: 12px;
	}
	.bar {
		flex: 1;
		height: 3px;
		border-radius: 2px;
		background: var(--border);
	}
	.bar[data-state='done'],
	.bar[data-state='active'] {
		background: var(--accent);
	}
	.bar[data-state='active'] {
		opacity: 0.7;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 0;
		position: relative;
		z-index: 2;
	}
	.close {
		min-width: 44px;
		min-height: 44px;
		border: 0;
		background: none;
		color: var(--text);
		font-size: 1.25rem;
		cursor: pointer;
	}
	.page {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 0.5rem;
		pointer-events: none; /* taps reach the Previous/Next zones; links opt back in */
	}
	.link {
		align-self: flex-start;
		position: relative;
		z-index: 2;
		pointer-events: auto;
		min-height: 44px;
		display: inline-flex;
		align-items: center;
		color: var(--accent);
	}
	.subject {
		margin: 0;
		font-size: 1.5rem;
		font-weight: 700;
		overflow-wrap: anywhere;
	}
	.meta {
		margin: 0;
		color: var(--muted);
	}
	.sha {
		align-self: flex-start;
		padding: 2px 8px;
		border-radius: 6px;
		background: var(--surface);
		border: 1px solid var(--border);
	}
	.zone {
		position: absolute;
		top: 72px;
		bottom: 0;
		width: 50%;
		border: 0;
		background: none;
		cursor: pointer;
		z-index: 1;
	}
	.left {
		left: 0;
	}
	.right {
		right: 0;
	}
</style>
