<script lang="ts">
	import CodePanel from './panels/CodePanel.svelte';
	import DiffPanel from './panels/DiffPanel.svelte';
	import ExplainPanel from './panels/ExplainPanel.svelte';
	import Avatar from './Avatar.svelte';
	import Poster from './Poster.svelte';
	import { visuals } from './visuals/index.ts';
	import type { Card, ResolvedCode, ResolvedDiff } from '#lib/types.ts';

	let { card, onPanelChange }: { card: Card; onPanelChange?: (panel: number) => void } = $props();
	let panel = $state(0);

	function onScroll(e: Event) {
		const el = e.currentTarget as HTMLElement;
		if (!el.clientWidth) return;
		const next = Math.round(el.scrollLeft / el.clientWidth);
		if (next === panel) return;
		panel = next;
		onPanelChange?.(next);
	}

	const Visual = $derived(visuals[card.visual.kind]);
	const count = $derived(1 + card.depth.length);
</script>

<article data-card-id={card.id}>
	<header>
		<a class="repo" href="/repo/{encodeURIComponent(card.repo)}">{card.repo}</a>
		<span class="persona">
			{#if card.account}
				<Poster account={card.account} kind={card.resolved.account?.kind} />
			{:else}
				<Poster account={card.persona} />
			{/if}
		</span>
		<span class="tone">{card.tone}</span>
	</header>
	<div class="panels" onscroll={onScroll}>
		<section data-panel="0">
			{#if Visual}
				<Visual visual={card.visual} resolved={card.resolved.visual} persona={card.persona} />
			{:else}
				<p class="unsupported">Unsupported card type: {card.visual.kind}</p>
			{/if}
			<h2>{card.hook}</h2>
			{#if card.comments.length}
				<ul class="comments">
					{#each card.comments as c, i (i)}
						<li><Avatar handle={c.persona} size={20} /><span class="handle">@{c.persona}</span>: {c.text}</li>
					{/each}
				</ul>
			{/if}
		</section>
		{#each card.depth as d, i (i)}
			<section data-panel={i + 1}>
				{#if d.kind === 'explain'}
					<ExplainPanel text={d.text} />
				{:else if d.kind === 'code'}
					<CodePanel
						repo={d.repo}
						path={d.path}
						commit={d.commit}
						resolved={(card.resolved.depth[i] as ResolvedCode | null) ?? null}
					/>
				{:else if d.kind === 'code_diff'}
					<DiffPanel
						repo={d.repo}
						path={d.path}
						commit={d.commit}
						diff={(card.resolved.depth[i] as ResolvedDiff | null)?.diff ?? ''}
					/>
				{/if}
			</section>
		{/each}
	</div>
	<div class="dots">
		{#each { length: count } as _, i (i)}
			<span class="dot" class:active={i === panel}></span>
		{/each}
	</div>
</article>

<style>
	article {
		height: 100dvh;
		scroll-snap-align: start;
		display: flex;
		flex-direction: column;
		padding: 0.75rem 16px;
	}
	header {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		font-size: 0.85rem;
	}
	.persona {
		color: var(--muted);
		min-width: 0;
	}
	.repo {
		color: inherit;
		font-weight: 600;
		text-decoration: none;
	}
	.repo:hover {
		text-decoration: underline;
	}
	.tone {
		margin-left: auto;
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.1rem 0.6rem;
		color: var(--muted);
	}
	.panels {
		flex: 1;
		min-height: 0;
		display: flex;
		overflow-x: auto;
		scroll-snap-type: x mandatory;
	}
	section {
		flex: 0 0 100%;
		scroll-snap-align: start;
		overflow-y: auto;
		padding: 1rem 0;
	}
	h2 {
		margin: 0;
		font-size: 1.5rem;
	}
	.unsupported {
		border: 1px dashed var(--border);
		border-radius: 8px;
		padding: 0.5rem;
		color: var(--muted);
		font-size: 0.85rem;
	}
	.comments {
		list-style: none;
		margin: 1rem 0 0;
		padding: 0;
		font-size: 0.9rem;
	}
	.comments li {
		margin-bottom: 0.4rem;
		display: flex;
		align-items: flex-start;
		gap: 0.4rem;
		overflow-wrap: anywhere;
	}
	.comments li :global(.avatar) {
		margin-top: 0.1rem;
	}
	.handle {
		color: var(--muted);
	}
	.dots {
		display: flex;
		justify-content: center;
		gap: 0.4rem;
		padding: 0.5rem 0;
	}
	.dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--border);
	}
	.dot.active {
		background: var(--accent);
	}
</style>
