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
	import { addSentReply, getAnswer, getFlags, setFlag, withSentReplies } from '#lib/cardState.ts';
	import { postReply } from '#lib/api.ts';
	import { setEagerImages } from '#lib/imageLoading.ts';
	import { scrollBehavior } from '#lib/motion.ts';
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
	// The first card is on screen at once; later cards load their images when they come near.
	setEagerImages(() => first);
	let answered = $state(card.interaction ? getAnswer(card.id) !== undefined : true);
	let liked = $state(getFlags(card.id).liked ?? false);
	let saved = $state(getFlags(card.id).saved ?? false);

	let disliked = $state(getFlags(card.id).disliked ?? false);

	// Like and thumbs-down exclude each other: turning one on turns the other off first.
	function toggle(flag: 'liked' | 'saved' | 'disliked') {
		const event = { liked: 'like', saved: 'save', disliked: 'dislike' } as const;
		const on = !{ liked, saved, disliked }[flag];
		const other = flag === 'liked' ? 'disliked' : flag === 'disliked' ? 'liked' : null;
		if (on && other && (other === 'liked' ? liked : disliked)) set(other, false, event[other]);
		set(flag, on, event[flag]);
	}

	function set(flag: 'liked' | 'saved' | 'disliked', on: boolean, type: FeedEventType) {
		if (flag === 'liked') liked = on;
		else if (flag === 'saved') saved = on;
		else disliked = on;
		setFlag(card.id, flag, on);
		onAction?.(type, { on });
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
	// so they open it from the Tap to expand pill or the corner button only.
	let lightboxOpen = $state(false);
	let visualEl: HTMLElement | undefined = $state();
	let clipped = $state(false);
	let shrunk = $state(false);
	const hint = $derived(clipped || shrunk);

	$effect(() => {
		const el = visualEl;
		if (!el || typeof ResizeObserver === 'undefined') return;
		const measure = () => (clipped = isClipped(el.scrollHeight, el.clientHeight));
		// While a bubble pops in, wait for its animationend (below): measuring mid-pop would
		// flash the hint on and off. The endless typing dots never end, so they do not count.
		const moving = () =>
			(el.getAnimations?.({ subtree: true }) ?? []).some(
				(a) => a.effect?.getTiming().iterations !== Infinity
			);
		const onResize = () => {
			if (!moving()) measure();
		};
		measure();
		// The box, and its content: content can grow (a new beat) in a box that keeps its size.
		const ro = new ResizeObserver(onResize);
		ro.observe(el);
		if (el.firstElementChild) ro.observe(el.firstElementChild);
		// A bubble pops in with a transform that sticks out of the box while it moves. No resize
		// marks its end, so measure again when an animation or transition inside ends.
		el.addEventListener('animationend', measure);
		el.addEventListener('transitionend', measure);
		return () => {
			ro.disconnect();
			el.removeEventListener('animationend', measure);
			el.removeEventListener('transitionend', measure);
		};
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
	let replies: Reply[] = $state(withSentReplies(card.id, card.replies ?? []));
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
			const reply = await postReply(card.id, idx, text);
			addSentReply(card.id, reply);
			replies = [...replies, reply];
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

	function goToPanel(i: number) {
		row?.scrollTo({ left: i * row.clientWidth, behavior: scrollBehavior() });
	}

	function openComments() {
		goToPanel(card.depth.length + 1);
	}

	const DEPTH_NAMES = { explain: 'Explanation', code: 'Code', code_diff: 'Diff' } as const;
	function panelLabel(i: number): string {
		const name =
			i === 0 ? 'Card' : i <= card.depth.length ? DEPTH_NAMES[card.depth[i - 1].kind] : 'Comments';
		return `Panel ${i + 1} of ${count}: ${name}`;
	}

	// Keyboard: left and right move between panels, Home and End jump to the ends. Up and down
	// scroll a long depth panel; everywhere else they are left to the feed (next and previous card).
	const KEY_SCROLL_PX = 80;
	function onKey(e: KeyboardEvent) {
		if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
		if ((e.target as Element | null)?.closest?.('input, textarea, select, [contenteditable]')) return;
		let next: number | null = null;
		if (e.key === 'ArrowRight') next = panel + 1;
		else if (e.key === 'ArrowLeft') next = panel - 1;
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = count - 1;
		if (next !== null) {
			if (next < 0 || next >= count || next === panel) return;
			e.preventDefault();
			goToPanel(next);
			return;
		}
		if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
		const section = row?.querySelector<HTMLElement>(`section[data-panel="${panel}"]`);
		if (!section || panel === 0 || section.scrollHeight <= section.clientHeight) return;
		const down = e.key === 'ArrowDown';
		// At the end of the panel the key goes on to the feed.
		if (down && section.scrollTop + section.clientHeight >= section.scrollHeight - 1) return;
		if (!down && section.scrollTop <= 0) return;
		e.preventDefault();
		section.scrollBy({ top: down ? KEY_SCROLL_PX : -KEY_SCROLL_PX, behavior: scrollBehavior() });
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
		{#if card.series}
			<span class="series">Part {card.series.part}/{card.series.of}</span>
		{/if}
	</header>
	<!-- A carousel: focus it, then use the arrow keys. svelte-ignore: a group that takes keys. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
	<div
		class="panels"
		role="group"
		aria-roledescription="carousel"
		aria-label="Card panels, panel {panel + 1} of {count}. Use the left and right arrow keys."
		tabindex="0"
		bind:this={row}
		onscroll={onScroll}
		onkeydown={onKey}
	>
		<section
			data-panel="0"
			class="front"
			role="group"
			aria-roledescription="slide"
			aria-label={panelLabel(0)}
		>
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
						<div class="fade">
							<button type="button" class="pill-hint" onclick={openLightbox}>Tap to expand</button>
						</div>
					{/if}
					<!-- Only on a card that plays in steps: there a tap moves to the next step, so a
					     button opens full screen (all steps at once). Elsewhere a tap on the visual opens
					     it, and Tap to expand shows when it is cut off. Bottom left: Replay holds the
					     top right, and the side buttons reach into the bottom right. -->
					{#if !hint && beats.length > 0}
						<button type="button" class="expand" aria-label="Expand" onclick={openLightbox}>⤢</button>
					{/if}
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
			<section
				data-panel={i + 1}
				role="group"
				aria-roledescription="slide"
				aria-label={panelLabel(i + 1)}
			>
				{#if d.kind === 'explain'}
					<ExplainPanel
						text={d.text}
						sources={card.links?.sources ?? []}
						learn={i === firstExplain ? card.learn : undefined}
						claims={i === firstExplain ? (card.claims ?? []) : []}
						claimUrls={card.links?.claims ?? []}
						checked={i === firstExplain && (card.resolved.facts?.length ?? 0) > 0}
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
			<section
				data-panel={card.depth.length + 1}
				class="comments-panel"
				role="group"
				aria-roledescription="slide"
				aria-label={panelLabel(card.depth.length + 1)}
			>
				<ul class="comments">
					{#each visibleComments as c (c.idx)}
						{@render commentRow(c, 'panel')}
					{/each}
				</ul>
			</section>
		{/if}
	</div>
	{#if lightboxOpen}
		<Lightbox {card} {Visual} onClose={() => (lightboxOpen = false)} />
	{/if}
	<div class="actions">
		<!-- 👍 and 👎 sit together; an emoji cannot be outlined, so off is shown faded and grey. -->
		<button type="button" aria-pressed={liked} aria-label="Like" onclick={() => toggle('liked')}>
			<span class="icon thumb" aria-hidden="true">👍</span>
			<span class="label" aria-hidden="true">Like</span>
		</button>
		<button
			type="button"
			aria-pressed={disliked}
			aria-label="Show less like this"
			onclick={() => toggle('disliked')}
		>
			<span class="icon thumb" aria-hidden="true">👎</span>
			<span class="label" aria-hidden="true">Less</span>
		</button>
		<button type="button" aria-pressed={saved} aria-label="Save" onclick={() => toggle('saved')}>
			<span class="icon" aria-hidden="true">{saved ? '★' : '☆'}</span>
			<span class="label" aria-hidden="true">Save</span>
		</button>
	</div>
	<div class="bottom-row">
		<!-- The panel row's label says the same in words. -->
		<div class="dots" aria-hidden="true">
			{#each { length: count } as _, i (i)}
				<span class="dot" class:active={i === panel}></span>
			{/each}
		</div>
	</div>
</article>

<style>
	article {
		position: relative;
		height: 100dvh;
		scroll-snap-align: start;
		display: flex;
		flex-direction: column;
		/* Clear of the notch, the rounded corners and the home indicator. */
		padding: max(0.75rem, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right))
			calc(0.75rem + env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
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
	.panels {
		flex: 1;
		min-height: 0;
		display: flex;
		overflow-x: auto;
		overflow-y: hidden;
		scroll-snap-type: x mandatory;
	}
	.panels:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
		border-radius: 4px;
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
	/* Bottom right: the top right holds the beat progress bar and Replay button. */
	.expand {
		position: absolute;
		bottom: 0;
		left: 0;
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
		pointer-events: auto; /* the fade lets taps through; the pill itself is a button */
		min-height: 32px;
		cursor: pointer;
		font: inherit;
		padding: 0.15rem 0.9rem;
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
		right: calc(10px + env(safe-area-inset-right));
		bottom: calc(3.5rem + env(safe-area-inset-bottom)); /* above the bottom row */
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
		justify-content: center;
		gap: 0.5rem;
	}
	.actions .icon {
		font-size: 1.2rem;
	}
	.actions .thumb {
		filter: grayscale(1);
		opacity: 0.55;
		transition:
			filter 0.15s,
			opacity 0.15s;
	}
	.actions button[aria-pressed='true'] .thumb {
		filter: none;
		opacity: 1;
	}
	.actions .label {
		font-size: 0.6rem;
		color: var(--muted);
	}
	.actions button[aria-pressed='true'] {
		background: color-mix(in srgb, var(--accent) 18%, var(--surface));
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
