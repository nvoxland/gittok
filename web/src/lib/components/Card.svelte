<script lang="ts">
	import Beats from './Beats.svelte';
	import { beatsFor } from '#lib/beats.ts';
	import CodePanel from './panels/CodePanel.svelte';
	import DiffPanel from './panels/DiffPanel.svelte';
	import ExplainPanel from './panels/ExplainPanel.svelte';
	import Avatar from './Avatar.svelte';
	import Quiz from './Quiz.svelte';
	import Lightbox from './Lightbox.svelte';
	import { isClipped } from '#lib/lightbox.ts';
	import Poster from './Poster.svelte';
	import { visuals } from './visuals/index.ts';
	import { getAnswer, getFlags, setFlag } from '#lib/cardState.ts';
	import { postReply } from '#lib/api.ts';
	import type { Card, FeedEventType, Reply, ResolvedCode, ResolvedDiff } from '#lib/types.ts';

	let {
		card,
		onPanelChange,
		onAction,
		first = false,
		active
	}: {
		card: Card;
		first?: boolean;
		// Set only by the feed: the card on screen plays its beats. Elsewhere cards are static.
		active?: boolean;
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

	let knewIt = $state(getFlags(card.id).knewIt ?? false);
	let teachMore = $state(getFlags(card.id).teachMore ?? false);

	// One-shot signals: the first tap fills the button and emits; later taps do nothing.
	function signal(flag: 'knewIt' | 'teachMore') {
		if (flag === 'knewIt' ? knewIt : teachMore) return;
		if (flag === 'knewIt') knewIt = true;
		else teachMore = true;
		setFlag(card.id, flag, true);
		onAction?.(flag === 'knewIt' ? 'knew_it' : 'teach_more', { on: true });
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

	// Lightbox: the visual at natural size. Beat cards keep tap = skip a beat,
	// so they open it from the corner button only.
	let lightboxOpen = $state(false);
	let visualEl: HTMLElement | undefined = $state();
	let clipped = $state(false);
	let shrunk = $state(false);
	const hint = $derived(clipped || shrunk);

	$effect(() => {
		const el = visualEl;
		if (!el || typeof ResizeObserver === 'undefined') return;
		const measure = () => (clipped = isClipped(el.scrollHeight, el.clientHeight));
		measure();
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		return () => ro.disconnect();
	});

	function openLightbox() {
		if (lightboxOpen) return;
		lightboxOpen = true;
		onAction?.('lightbox_open', { kind: card.visual.kind });
	}

	function tapVisual(e: MouseEvent) {
		if (beats.length) return;
		if ((e.target as Element | null)?.closest?.('a, button, input, label')) return;
		openLightbox();
	}

	const Visual = $derived(visuals[card.visual.kind]);
	const beats = $derived(active === undefined ? [] : beatsFor(card.visual));
	// Comments wait for a quiz answer: they can give it away.
	const firstExplain = $derived(card.depth.findIndex((d) => d.kind === 'explain'));
	// A comment is a spoiler unless it says otherwise on a quiz card; other cards show them all.
	// `idx` is the comment's place in the card's full list: replies are stored against it.
	const visibleComments = $derived(
		(card.comments ?? [])
			.map((c, idx) => ({ ...c, idx }))
			.filter((c) => answered || !(c.spoiler ?? !!card.interaction))
	);

	// The reader's replies (shown only to them), the open reply box, and its draft.
	let replies: Reply[] = $state(card.replies ?? []);
	let replyOpen: string | null = $state(null);
	let draft = $state('');
	let replyError = $state('');
	let sending = $state(false);

	function toggleReply(key: string) {
		replyOpen = replyOpen === key ? null : key;
		draft = '';
		replyError = '';
	}

	async function sendReply(idx: number) {
		const text = draft.trim();
		if (!text || sending) return;
		sending = true;
		replyError = '';
		try {
			replies = [...replies, await postReply(card.id, idx, text)];
			replyOpen = null;
			draft = '';
		} catch {
			replyError = 'Could not send the reply.';
		} finally {
			sending = false;
		}
	}
	const showComments = $derived(visibleComments.length > 0);
	const count = $derived(1 + card.depth.length + (showComments ? 1 : 0));

	function openComments() {
		row?.scrollTo({ left: (card.depth.length + 1) * row.clientWidth, behavior: 'smooth' });
	}
</script>

{#snippet commentRow(c: { persona: string; text: string; idx: number }, where: string)}
	<li>
		<Avatar handle={c.persona} size={20} />
		<div class="comment-body">
			<span><a class="handle" href="/persona/{encodeURIComponent(c.persona)}">@{c.persona}</a>: {c.text}</span>
			{#each replies.filter((r) => r.comment_index === c.idx) as r (r.id)}
				<div class="reply">
					<span class="you">You</span>: <span>{r.text}</span>
					{#if r.answered_card_id}
						<a class="answered" href="/card/{encodeURIComponent(r.answered_card_id)}">@{r.persona} answered →</a>
					{/if}
				</div>
			{/each}
			<button type="button" class="reply-btn" onclick={() => toggleReply(`${where}:${c.idx}`)}>
				Reply
			</button>
			{#if replyOpen === `${where}:${c.idx}`}
				<form
					class="reply-form"
					onsubmit={(e) => {
						e.preventDefault();
						sendReply(c.idx);
					}}
				>
					<textarea
						aria-label="Your reply"
						maxlength="280"
						rows="2"
						bind:value={draft}
					></textarea>
					<button type="submit" disabled={!draft.trim() || sending}>Send</button>
					{#if replyError}<span class="reply-error" role="alert">{replyError}</span>{/if}
				</form>
			{/if}
		</div>
	</li>
{/snippet}

<article data-card-id={card.id} class:first>
	<header>
		<a class="repo" href="/repo/{encodeURIComponent(card.repo)}">{card.repo}</a>
		<span class="persona">
			{#if card.account}
				<Poster account={card.account} kind={card.resolved.account?.kind} />
			{:else}
				<Poster account={card.persona} />
			{/if}
		</span>
		{#if card.series}
			<span class="series">Part {card.series.part}/{card.series.of}</span>
		{/if}
		<span class="tone">{card.tone}</span>
	</header>
	<div class="panels" bind:this={row} onscroll={onScroll}>
		<section data-panel="0" class="front">
			<!-- Keyboard and screen reader users open it with the Expand button. -->
			<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
			<div class="visual" bind:this={visualEl} onclick={tapVisual}>
				{#if Visual}
					<Beats cardId={card.id} {beats} active={!!active} onAction={(t, d) => onAction?.(t, d)}>
						{#snippet children(shown: number)}
							<Visual
								visual={card.visual}
								resolved={card.resolved.visual}
								persona={card.persona}
								{shown}
								onShrunk={(v: boolean) => (shrunk = v)}
							/>
						{/snippet}
					</Beats>
					{#if hint}
						<div class="fade" aria-hidden="true"><span class="pill-hint">Tap to expand</span></div>
					{/if}
					<button type="button" class="expand" aria-label="Expand" onclick={openLightbox}>⤢</button>
				{:else}
					<p class="unsupported">Unsupported card type: {card.visual.kind}</p>
				{/if}
			</div>
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
			{#if showComments}
				<ul class="face-comments">
					{#each visibleComments.slice(0, 2) as c (c.idx)}
						{@render commentRow(c, 'face')}
					{/each}
				</ul>
				{#if visibleComments.length > 2}
					<button type="button" class="comment-preview" onclick={openComments}>
						All {visibleComments.length} comments
					</button>
				{/if}
			{/if}
		</section>
		{#each card.depth as d, i (i)}
			<section data-panel={i + 1}>
				{#if d.kind === 'explain'}
					<ExplainPanel
						text={d.text}
						sources={card.links?.sources ?? []}
						learn={i === firstExplain ? card.learn : undefined}
					/>
				{:else if d.kind === 'code'}
					<CodePanel
						repo={d.repo}
						path={d.path}
						commit={d.commit}
						url={card.links?.panels[i] ?? null}
						resolved={(card.resolved.depth[i] as ResolvedCode | null) ?? null}
						onSourceTap={() => onAction?.('source_tap', { panel: i + 1 })}
					/>
				{:else if d.kind === 'code_diff'}
					<DiffPanel
						repo={d.repo}
						path={d.path}
						commit={d.commit}
						url={card.links?.panels[i] ?? null}
						diff={(card.resolved.depth[i] as ResolvedDiff | null)?.diff ?? ''}
						onSourceTap={() => onAction?.('source_tap', { panel: i + 1 })}
					/>
				{/if}
			</section>
		{/each}
		{#if showComments}
			<section data-panel={card.depth.length + 1} class="comments-panel">
				<ul class="comments">
					{#each visibleComments as c (c.idx)}
						{@render commentRow(c, 'panel')}
					{/each}
				</ul>
			</section>
		{/if}
	</div>
	{#if lightboxOpen && Visual}
		<Lightbox {card} {Visual} onClose={() => (lightboxOpen = false)} />
	{/if}
	<div class="actions">
		<button type="button" aria-pressed={liked} aria-label="Like" onclick={() => toggle('liked')}>
			<span class="icon" aria-hidden="true">{liked ? '♥' : '♡'}</span>
			<span class="label" aria-hidden="true">Like</span>
		</button>
		<button type="button" aria-pressed={saved} aria-label="Save" onclick={() => toggle('saved')}>
			<span class="icon" aria-hidden="true">{saved ? '★' : '☆'}</span>
			<span class="label" aria-hidden="true">Save</span>
		</button>
		{#if showComments}
			<!-- Jumps to the comments panel; the panel change itself is the depth_open signal. -->
			<button
				type="button"
				class="comments-btn"
				aria-label="Comments ({visibleComments.length})"
				onclick={openComments}
			>
				<span aria-hidden="true">💬</span><span class="count">{visibleComments.length}</span>
			</button>
		{/if}
	</div>
	<!-- Knowledge signals ride in the dots row so the side column stays short. -->
	<div class="bottom-row">
		<button
			type="button"
			class="pill"
			aria-pressed={knewIt}
			aria-label="Knew it"
			onclick={() => signal('knewIt')}
		>
			<span class="icon" aria-hidden="true">{knewIt ? '✔' : '✓'}</span>
			<span class="label" aria-hidden="true">Knew it</span>
		</button>
		<div class="dots">
			{#each { length: count } as _, i (i)}
				<span class="dot" class:active={i === panel}></span>
			{/each}
		</div>
		<button
			type="button"
			class="pill"
			aria-pressed={teachMore}
			aria-label="Teach me more"
			onclick={() => signal('teachMore')}
		>
			<span class="icon" aria-hidden="true">{teachMore ? '⊕' : '＋'}</span>
			<span class="label" aria-hidden="true">More</span>
		</button>
	</div>
</article>

<style>
	article {
		position: relative;
		height: 100dvh;
		scroll-snap-align: start;
		display: flex;
		flex-direction: column;
		padding: 0.75rem 16px;
	}
	/* The first card shares the screen with the top bar and snaps by its bottom edge, so
	   scrolling back to it shows the bar again. */
	article.first {
		height: calc(100dvh - var(--chrome-h, 0px));
		scroll-snap-align: end;
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
		overflow-y: hidden;
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
	/* The front never scrolls: on iOS an inner vertical scroller takes the swipe and the
	   feed never flips. The visual shrinks and clips; the hook always shows. */
	.front {
		overflow: hidden;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.visual {
		position: relative;
		flex: 0 1 auto;
		min-height: 0;
		overflow: hidden;
	}
	.expand {
		position: absolute;
		top: 0;
		right: 0;
		z-index: 2;
		width: 32px;
		height: 32px;
		padding: 0;
		border: 0;
		border-radius: 8px;
		background: color-mix(in srgb, var(--surface) 75%, transparent);
		color: var(--muted);
		font-size: 1rem;
		line-height: 1;
		cursor: pointer;
	}
	.fade {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 1;
		height: 4rem;
		display: flex;
		align-items: flex-end;
		justify-content: center;
		padding-bottom: 0.4rem;
		pointer-events: none;
		background: linear-gradient(to bottom, transparent, var(--bg) 85%);
	}
	.pill-hint {
		padding: 0.15rem 0.7rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--muted);
		font-size: 0.75rem;
	}
	h2 {
		flex: none;
		margin: 0;
		padding-right: 52px; /* clear of the side buttons (44px + gap) */
		font-size: 1.25rem;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 6;
		line-clamp: 6;
		overflow: hidden;
	}
	.unsupported {
		border: 1px dashed var(--border);
		border-radius: 8px;
		padding: 0.5rem;
		color: var(--muted);
		font-size: 0.85rem;
	}
	.comment-preview {
		flex: none;
		display: block;
		padding: 0;
		border: 0;
		background: none;
		color: var(--muted);
		font: inherit;
		font-size: 0.8rem;
		text-align: left;
		cursor: pointer;
	}
	.face-comments {
		flex: none;
		list-style: none;
		margin: 0;
		padding: 0 52px 0 0; /* clear of the side buttons */
		font-size: 0.85rem;
		color: var(--muted);
	}
	.face-comments li {
		display: flex;
		gap: 0.4rem;
		align-items: flex-start;
		margin-bottom: 0.3rem;
		min-width: 0;
	}
	.face-comments li > span {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
	}
	.series {
		flex: none;
		border-radius: 999px;
		padding: 0.1rem 0.5rem;
		background: color-mix(in srgb, var(--accent) 18%, var(--surface));
		color: var(--accent);
		font-size: 0.75rem;
		white-space: nowrap;
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
	.comment-body {
		display: grid;
		gap: 0.25rem;
		min-width: 0;
	}
	.reply {
		padding-left: 0.6rem;
		border-left: 2px solid var(--border);
	}
	.you {
		font-weight: 600;
	}
	.answered {
		margin-left: 0.4rem;
		color: var(--accent);
	}
	.reply-btn {
		justify-self: start;
		padding: 0;
		border: 0;
		background: none;
		color: var(--muted);
		font-size: 0.75rem;
		cursor: pointer;
	}
	.reply-form {
		display: grid;
		gap: 0.3rem;
	}
	.reply-form textarea {
		width: 100%;
		box-sizing: border-box;
		font: inherit;
		background: var(--surface);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	.reply-form button {
		justify-self: start;
	}
	.reply-error {
		color: var(--muted);
		font-size: 0.75rem;
	}
	.handle {
		color: var(--muted);
		text-decoration: none;
	}
	.handle:hover {
		text-decoration: underline;
	}
	.actions {
		position: absolute;
		right: 10px;
		bottom: 3.5rem; /* above the bottom row */
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.actions button {
		width: 44px;
		min-height: 44px;
		padding: 2px 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1px;
		line-height: 1;
		border-radius: 50%;
		border: none;
		background: color-mix(in srgb, var(--surface) 70%, transparent);
		color: inherit;
		font-size: 1.2rem;
		cursor: pointer;
	}
	.bottom-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.bottom-row .pill {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		min-height: 36px;
		padding: 0 0.75rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: inherit;
		font-size: 0.8rem;
		cursor: pointer;
	}
	.bottom-row .pill .label {
		color: var(--muted);
	}
	.bottom-row .pill[aria-pressed='true'] {
		color: var(--accent);
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 18%, var(--surface));
	}
	.actions .icon {
		font-size: 1.2rem;
	}
	.actions .label {
		font-size: 0.6rem;
		color: var(--muted);
	}
	.actions button[aria-pressed='true'] {
		background: color-mix(in srgb, var(--accent) 18%, var(--surface));
	}
	.comments-btn {
		display: grid;
		place-items: center;
		align-content: center;
		gap: 0;
		line-height: 1;
	}
	.comments-btn span:first-child {
		font-size: 1rem;
	}
	.comments-btn .count {
		font-size: 0.65rem;
		color: var(--muted);
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
