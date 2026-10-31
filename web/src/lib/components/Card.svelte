<script lang="ts">
	import CodePanel from './panels/CodePanel.svelte';
	import DiffPanel from './panels/DiffPanel.svelte';
	import ExplainPanel from './panels/ExplainPanel.svelte';
	import Avatar from './Avatar.svelte';
	import Quiz from './Quiz.svelte';
	import Poster from './Poster.svelte';
	import { visuals } from './visuals/index.ts';
	import { getAnswer, getFlags, setFlag } from '#lib/cardState.ts';
	import type { Card, FeedEventType, ResolvedCode, ResolvedDiff } from '#lib/types.ts';

	let {
		card,
		onPanelChange,
		onAction
	}: {
		card: Card;
		onPanelChange?: (panel: number) => void;
		onAction?: (type: FeedEventType, data?: Record<string, unknown>) => void;
	} = $props();
	let row: HTMLElement | undefined = $state();
	let answered = $state(card.interaction ? getAnswer(card.id) !== undefined : true);
	let liked = $state(getFlags(card.id).liked ?? false);
	let saved = $state(getFlags(card.id).saved ?? false);

	function toggle(flag: 'liked' | 'saved') {
		const on = flag === 'liked' ? !liked : !saved;
		if (flag === 'liked') liked = on;
		else saved = on;
		setFlag(card.id, flag, on);
		onAction?.(flag === 'liked' ? 'like' : 'save', { on });
	}

	function explainMore() {
		const i = card.depth.findIndex((d) => d.kind === 'explain');
		if (row && i >= 0) row.scrollTo({ left: (i + 1) * row.clientWidth, behavior: 'smooth' });
		onAction?.('explain_more', {});
	}
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
	<div class="panels" bind:this={row} onscroll={onScroll}>
		<section data-panel="0">
			{#if Visual}
				<Visual visual={card.visual} resolved={card.resolved.visual} persona={card.persona} />
			{:else}
				<p class="unsupported">Unsupported card type: {card.visual.kind}</p>
			{/if}
			{#if card.interaction}
				<Quiz
					cardId={card.id}
					interaction={card.interaction}
					onAnswer={() => {
						// POST /api/answer records the answer event server-side; do not emit another.
						answered = true;
					}}
				/>
			{/if}
			<h2>{card.hook}</h2>
			{#if card.comments?.length && answered}
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
						onSourceTap={() => onAction?.('source_tap', { panel: i + 1 })}
					/>
				{:else if d.kind === 'code_diff'}
					<DiffPanel
						repo={d.repo}
						path={d.path}
						commit={d.commit}
						diff={(card.resolved.depth[i] as ResolvedDiff | null)?.diff ?? ''}
						onSourceTap={() => onAction?.('source_tap', { panel: i + 1 })}
					/>
				{/if}
			</section>
		{/each}
	</div>
	<div class="actions">
		<button type="button" aria-pressed={liked} aria-label="Like" onclick={() => toggle('liked')}>
			{liked ? '♥' : '♡'}
		</button>
		<button type="button" aria-pressed={saved} aria-label="Save" onclick={() => toggle('saved')}>
			{saved ? '★' : '☆'}
		</button>
		<button type="button" aria-label="Explain more" onclick={explainMore}>?</button>
	</div>
	<div class="dots">
		{#each { length: count } as _, i (i)}
			<span class="dot" class:active={i === panel}></span>
		{/each}
	</div>
</article>

<style>
	article {
		position: relative;
		height: 100%;
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
		display: flex;
	}
	.repo {
		flex: 0 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: inherit;
		font-weight: 600;
		text-decoration: none;
	}
	.repo:hover {
		text-decoration: underline;
	}
	.tone {
		flex: none;
		margin-left: auto;
		white-space: nowrap;
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
		min-width: 0;
		overflow-y: auto;
		overflow-wrap: anywhere; /* long paths and identifiers wrap instead of widening the card */
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
	.actions {
		position: absolute;
		right: 12px;
		bottom: 3.5rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.actions button {
		width: 44px;
		height: 44px;
		border-radius: 50%;
		border: 1px solid var(--border);
		background: var(--surface);
		color: inherit;
		font-size: 1.2rem;
		cursor: pointer;
	}
	.actions button[aria-pressed='true'] {
		color: var(--accent);
		border-color: var(--accent);
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
