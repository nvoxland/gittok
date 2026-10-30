<script lang="ts">
	import { relativeTime } from '#lib/relativeTime.ts';
	import type { Story } from '#lib/types.ts';

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

	let index = $state(0);
	const shown = new Set<string>();
	const commit = $derived(story.commits[index]);

	$effect(() => {
		const sha = commit?.sha;
		if (sha && !shown.has(sha)) {
			shown.add(sha);
			onSeen?.(story.repo, [sha]);
		}
	});

	function next() {
		if (index >= story.commits.length - 1) onClose();
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
	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
		else if (e.key === 'ArrowRight') next();
		else if (e.key === 'ArrowLeft') prev();
	}
</script>

<svelte:window onkeydown={onKey} />

<div
	class="viewer"
	role="dialog"
	aria-modal="true"
	aria-label="{story.repo} story"
	tabindex="-1"
	ontouchstart={onTouchStart}
	ontouchend={onTouchEnd}
>
	<div class="bars">
		{#each story.commits as c, i (c.sha)}
			<span
				class="bar"
				data-testid="progress"
				data-state={i < index ? 'done' : i === index ? 'active' : 'upcoming'}
			></span>
		{/each}
	</div>
	<div class="head">
		<strong>{story.repo}</strong>
		<button type="button" class="close" aria-label="Close" onclick={onClose}>&#10005;</button>
	</div>
	{#if commit}
		<div class="page">
			<p class="subject">{commit.subject}</p>
			<p class="meta">{commit.author} · {relativeTime(commit.ts, now)}</p>
			<p class="meta">{commit.files} {commit.files === 1 ? 'file' : 'files'}</p>
			<code class="sha">{commit.short}</code>
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
