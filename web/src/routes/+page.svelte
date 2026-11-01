<script lang="ts">
	import { onMount } from 'svelte';
	import Feed from '#lib/components/Feed.svelte';
	import StoriesRow from '#lib/components/StoriesRow.svelte';
	import StoryViewer from '#lib/components/StoryViewer.svelte';
	import CatchUp from '#lib/components/CatchUp.svelte';
	import NotificationBell from '#lib/components/NotificationBell.svelte';
	import { fetchFeed, fetchPrefs, fetchStories, markStoriesSeen, postEvents } from '#lib/api.ts';
	import { setPlaybackSpeed } from '#lib/beats.ts';
	import { createBatcher } from '#lib/batcher.ts';
	import { clearAnswers } from '#lib/cardState.ts';
	import type { Card, FeedFilter, Story } from '#lib/types.ts';

	// /?repo=x&dir=y shows only cards under that dir; a chip in the top bar clears it.
	function readFilter(): FeedFilter {
		const q = new URLSearchParams(typeof window === 'undefined' ? '' : window.location.search);
		const f: FeedFilter = {};
		if (q.get('repo')) f.repo = q.get('repo')!;
		if (q.get('dir')) f.dir = q.get('dir')!;
		return f;
	}
	let filter = $state<FeedFilter>(readFilter());
	const filtered = $derived(!!(filter.repo || filter.dir));

	function clearFilter() {
		filter = {};
		window.history.replaceState({}, '', window.location.pathname);
		cards = [];
		nextCursor = null;
		atEnd = false;
		loading = true;
		void load();
	}

	let cards = $state<Card[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let fromCache = $state(false);
	let nextCursor: string | null = null;
	// No more pages: the feed ends with the caught-up card.
	let atEnd = $state(false);
	let checking = $state(false);
	let checkedEmpty = $state(false);
	let loadingMore = false;
	let stories = $state<Story[]>([]);
	let openStory = $state<number | null>(null);
	let catchingUp = $state(false);
	let chromeH = $state(0);

	const batcher = createBatcher(postEvents, 5000);

	onMount(() => {
		batcher.start();
		const onVis = () => {
			if (document.visibilityState === 'hidden') void batcher.flush();
		};
		document.addEventListener('visibilitychange', onVis);
		void load();
		void loadStories();
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			batcher.stop();
		};
	});

	async function loadStories() {
		try {
			stories = await fetchStories();
		} catch {
			stories = [];
		}
	}

	const seenShas = new Set<string>();
	function onSeen(repo: string, shas: string[]) {
		void markStoriesSeen(repo, shas).catch(() => {});
		shas.forEach((sha) => seenShas.add(sha));
		// The ring updates now; the viewer keeps showing its own copy until it closes.
		stories = stories.map((st) =>
			st.repo === repo && st.commits.every((c) => seenShas.has(c.sha)) ? { ...st, seen: true } : st
		);
	}

	async function load() {
		try {
			// The speed must be set before beat cards mount; a failed prefs call keeps the default.
			const [feed, prefs] = await Promise.all([fetchFeed(undefined, 20, filter), fetchPrefs().catch(() => null)]);
			if (prefs) setPlaybackSpeed(prefs.playback_speed);
			fromCache = !!feed.fromCache;
			const fresh = feed.cards;
			// Cards the server serves again are new or due for review: let them be answered again.
			// The resumed card is the one on screen before the reload: keep its answer.
			clearAnswers(fresh.map((c) => c.id).filter((id) => id !== feed.resume_card_id));
			cards = fresh;
			nextCursor = feed.next_cursor;
			atEnd = nextCursor === null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	// The next page, asked for by the feed near its end. Cards already shown are skipped.
	async function loadMore() {
		if (!nextCursor || loadingMore) return;
		loadingMore = true;
		try {
			const feed = await fetchFeed(nextCursor, 20, filter);
			const have = new Set(cards.map((c) => c.id));
			const fresh = feed.cards.filter((c) => !have.has(c.id));
			clearAnswers(fresh.map((c) => c.id));
			cards = [...cards, ...fresh];
			nextCursor = feed.next_cursor;
			atEnd = nextCursor === null;
		} catch {
			// Keep the cursor; the next card near the end tries again.
		} finally {
			loadingMore = false;
		}
	}

	// From the caught-up card: ask for a fresh first page and add the cards not shown yet.
	async function checkAgain() {
		checking = true;
		checkedEmpty = false;
		try {
			const feed = await fetchFeed(undefined, 20, filter);
			const have = new Set(cards.map((c) => c.id));
			const fresh = feed.cards.filter((c) => !have.has(c.id));
			clearAnswers(fresh.map((c) => c.id));
			cards = [...cards, ...fresh];
			nextCursor = feed.next_cursor;
			atEnd = nextCursor === null;
			checkedEmpty = fresh.length === 0;
		} catch {
			checkedEmpty = true;
		} finally {
			checking = false;
		}
	}
</script>

<!-- The page scrolls; the top bar scrolls away with the first card. -->
<div class="app" style="--chrome-h: {chromeH}px">
<header class="chrome" aria-label="Top bar" bind:offsetHeight={chromeH}>
	<div class="stories-slot"><StoriesRow {stories} onOpen={(i) => (openStory = i)} onCatchUp={() => (catchingUp = true)} /></div>
	<nav class="links">
		{#if filtered}
			<span class="filter" data-testid="feed-filter">
				{[filter.repo, filter.dir].filter(Boolean).join('/')}
				<button type="button" aria-label="Clear filter" onclick={clearFilter}>&times;</button>
			</span>
		{/if}
		<a href="/saved">Saved</a>
		<NotificationBell />
	</nav>
</header>

{#if fromCache}
	<p class="offline" role="status">Offline &mdash; showing your last batch</p>
{/if}

{#if openStory !== null && stories[openStory]}
	{@const active = stories[openStory]}
	{#key active.repo}
		<StoryViewer story={active} {onSeen} onClose={() => (openStory = null)} />
	{/key}
{/if}

{#if catchingUp}
	<CatchUp {stories} {onSeen} onClose={() => (catchingUp = false)} />
{/if}

<main>
	{#if error}
		<p class="status error" role="alert">Failed to load feed: {error}</p>
	{:else if loading}
		<p class="status">Loading...</p>
	{:else}
		{#if cards.length > 0}
			<Feed {cards} onEvent={(e) => batcher.push(e)} onNearEnd={loadMore} />
		{/if}
		{#if atEnd}
			<section class="end" aria-label="End of feed">
				<h2>You're all caught up</h2>
				<p>You have seen every card for now.</p>
				<p>
					To make more, open Claude Code in the CodeScroll repo and run
					<code>/codescroll-generate</code>.
				</p>
				<button type="button" onclick={checkAgain} disabled={checking}>
					{checking ? 'Checking…' : 'Check for new cards'}
				</button>
				{#if checkedEmpty}
					<p class="muted" role="status">No new cards yet.</p>
				{/if}
			</section>
		{/if}
	{/if}
</main>
</div>

<style>
	/* The top bar takes its own row, so it never covers a card's header. */
	.chrome {
		display: flex;
		align-items: center;
		border-bottom: 1px solid var(--border);
	}
	.stories-slot {
		flex: 1;
		min-width: 0;
	}
	.links {
		flex: none;
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-left: auto;
		padding: 0 16px 0 8px;
	}
	.links a {
		display: inline-flex;
		align-items: center;
		min-height: 44px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
	.filter {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		max-width: 10rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0 0.25rem 0 0.6rem;
		font-size: 0.75rem;
		color: var(--muted);
	}
	.filter button {
		min-width: 44px;
		min-height: 44px;
		border: 0;
		background: none;
		color: inherit;
		font-size: 1rem;
		cursor: pointer;
	}
	.offline {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		z-index: 20;
		margin: 0;
		padding: 0.5rem 16px;
		background: var(--surface);
		border-top: 1px solid var(--border);
		color: var(--muted);
		font-size: 0.85rem;
		text-align: center;
	}
	.status {
		display: grid;
		place-items: center;
		height: calc(100dvh - var(--chrome-h, 0px));
		margin: 0;
		color: var(--muted);
	}
	.end {
		height: 100dvh;
		scroll-snap-align: start;
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 0.75rem;
		padding: 0 16px;
		text-align: center;
	}
	.end h2,
	.end p {
		margin: 0;
	}
	.end code {
		font-size: 0.95em;
	}
	.end button {
		align-self: center;
		margin-top: 0.5rem;
		padding: 0.6rem 1.2rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.end .muted {
		color: var(--muted);
		font-size: 0.9rem;
	}
	.error {
		color: #e5484d;
	}
</style>
