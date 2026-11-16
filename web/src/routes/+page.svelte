<script lang="ts">
	import { onMount, tick } from 'svelte';
	import Feed from '#lib/components/Feed.svelte';
	import StoriesRow from '#lib/components/StoriesRow.svelte';
	import StoryViewer from '#lib/components/StoryViewer.svelte';
	import NotificationBell from '#lib/components/NotificationBell.svelte';
	import GestureHints from '#lib/components/GestureHints.svelte';
	import {
		ApiError,
		fetchCard,
		fetchFeed,
		fetchPrefs,
		fetchRepos,
		fetchStories,
		markStoriesSeen,
		postEvents
	} from '#lib/api.ts';
	import { setPlaybackSpeed } from '#lib/beats.ts';
	import { createBatcher } from '#lib/batcher.ts';
	import { clearAnswers } from '#lib/cardState.ts';
	import type { Card, FeedEvent, FeedFilter, Story } from '#lib/types.ts';

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
		void load();
	}

	let cards = $state<Card[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	// HTTP 401: this device has no pairing cookie (a LAN device that never paired by code).
	let unpaired = $state(false);
	let pairing = $state(false);
	let pairError = $state<string | null>(null);
	// A failed next page or a failed "check for new cards": shown with a retry, never hidden.
	let moreError = $state<string | null>(null);
	let checkError = $state<string | null>(null);
	// No cards and no configured repos: a new install, not a feed that is caught up.
	let noRepos = $state(false);
	let fromCache = $state(false);
	let nextCursor: string | null = null;
	// Names every card the server sent this session, also at the end of the feed (where
	// next_cursor is null). Asked with it, the server sends only cards made since.
	let sentCursor: string | null = null;
	// No more pages: the feed ends with the caught-up card.
	let atEnd = $state(false);
	// A generation run is open on the server now (from the newest feed answer, never from cache).
	let generating = $state(false);
	let checking = $state(false);
	let checkedEmpty = $state(false);
	let endPanel: HTMLElement | undefined = $state();
	let loadingMore = false;
	let stories = $state<Story[]>([]);
	let openStory = $state<number | null>(null);
	let chromeH = $state(0);

	// The card on screen, kept on this device so a reload (iOS drops background pages) resumes on it
	// even when the server's event log has not caught up. localStorage, not sessionStorage: a
	// browser restart or tab restore (Brave on iOS) starts a new session and would lose it.
	const CURRENT_KEY = 'gittok.current';
	function rememberCurrent(id: string) {
		try {
			localStorage.setItem(CURRENT_KEY, id);
		} catch {
			// storage unavailable: the server resume card still applies
		}
	}
	function readCurrent(): string | null {
		try {
			return localStorage.getItem(CURRENT_KEY);
		} catch {
			return null;
		}
	}

	// Put the remembered card first, so nothing unseen sits above the view. Drops the server's
	// resume card when the remembered one is newer.
	async function resumeOn(fresh: Card[], resumeId: string | null | undefined): Promise<Card[]> {
		const id = readCurrent();
		if (!id || filtered || fresh[0]?.id === id) return fresh;
		let card = fresh.find((c) => c.id === id);
		if (!card) {
			try {
				card = await fetchCard(id);
			} catch {
				return fresh; // gone: the server's resume card (first) stays
			}
		}
		return [card, ...fresh.filter((c) => c.id !== id && c.id !== resumeId)];
	}

	const batcher = createBatcher(postEvents, 5000);

	onMount(() => {
		// The browser would restore the old scroll offset against a rebuilt list.
		try {
			history.scrollRestoration = 'manual';
		} catch {
			// not supported
		}
		batcher.start();
		const onVis = () => {
			// iOS suspends a hidden page and can cancel a normal request: send with sendBeacon.
			if (document.visibilityState === 'hidden') batcher.flushOnExit();
			// Back at the end of the feed: a run may have made cards meanwhile.
			else if (atEnd && !checking) void checkAgain(true);
		};
		document.addEventListener('visibilitychange', onVis);
		const onShow = (event: PageTransitionEvent) => {
			if (event.persisted && unpaired) void load();
		};
		window.addEventListener('pageshow', onShow);
		void load();
		void loadStories();
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			window.removeEventListener('pageshow', onShow);
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

	const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

	/** Records a failed call. A 401 from any call means the whole page needs pairing. */
	function failed(e: unknown, set: (msg: string) => void) {
		if (e instanceof ApiError && e.status === 401) unpaired = true;
		else set(message(e));
	}

	async function pairWithCode(event: SubmitEvent) {
		event.preventDefault();
		if (pairing) return;
		pairing = true;
		pairError = null;
		try {
			const response = await fetch('/pair/code', { method: 'POST', credentials: 'same-origin' });
			if (!response.ok) throw new Error('pairing request failed');
			window.location.replace('/pair/wait');
		} catch {
			pairError = 'Could not get a pairing code. Try again.';
		} finally {
			pairing = false;
		}
	}

	// The page opens on the first card, a full screen like every other. The top bar sits above
	// it, a snap point of its own: scroll up to see the stories, Saved and the bell.
	async function showFirstCard() {
		await tick();
		document
			.querySelector('.feed [data-card-id]')
			?.scrollIntoView?.({ behavior: 'instant', block: 'start' });
	}

	async function load() {
		loading = true;
		error = null;
		unpaired = false;
		moreError = null;
		checkError = null;
		checkedEmpty = false;
		try {
			// The speed must be set before beat cards mount; a failed prefs call keeps the default.
			const [feed, prefs] = await Promise.all([fetchFeed(undefined, 20, filter), fetchPrefs().catch(() => null)]);
			if (prefs) setPlaybackSpeed(prefs.playback_speed);
			fromCache = !!feed.fromCache;
			generating = !!feed.generating && !feed.fromCache;
			const fresh = await resumeOn(feed.cards, feed.resume_card_id);
			// Cards the server serves again are new or due for review: let them be answered again.
			// The resumed card is the one on screen before the reload: keep its answer.
			clearAnswers(fresh.map((c) => c.id).filter((id) => id !== feed.resume_card_id && id !== readCurrent()));
			// An empty feed with no repos is a new install. A failed repos call keeps the caught-up card.
			noRepos =
				fresh.length === 0 && !filtered
					? await fetchRepos().then((r) => r.length === 0, () => false)
					: false;
			cards = fresh;
			void showFirstCard();
			nextCursor = feed.next_cursor;
			sentCursor = feed.cursor ?? feed.next_cursor ?? sentCursor;
			atEnd = nextCursor === null;
		} catch (e) {
			failed(e, (msg) => (error = msg));
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
			sentCursor = feed.cursor ?? feed.next_cursor ?? sentCursor;
			atEnd = nextCursor === null;
			generating = !!feed.generating && !feed.fromCache;
			moreError = null;
		} catch (e) {
			// Keep the cursor: the Try again button and the next card near the end both try again.
			failed(e, (msg) => (moreError = msg));
		} finally {
			loadingMore = false;
		}
	}

	// A 👍 or 👎 only teaches the learner what to make next: it does not change the cards ahead.
	function onFeedEvent(e: FeedEvent) {
		batcher.push(e);
	}

	// While a run is making cards, the end card asks for them by itself.
	const POLL_WHILE_GENERATING_MS = 10_000;
	$effect(() => {
		if (!atEnd || !generating || loading) return;
		const timer = setInterval(() => {
			if (!checking) void checkAgain(true);
		}, POLL_WHILE_GENERATING_MS);
		return () => clearInterval(timer);
	});

	// From the caught-up card: ask for the cards not sent yet and add them. `quiet` (a check
	// the page makes by itself) shows no "No new cards yet" and no error.
	async function checkAgain(quiet = false) {
		checking = true;
		if (!quiet) {
			checkedEmpty = false;
			checkError = null;
		}
		try {
			const feed = await fetchFeed(sentCursor ?? undefined, 20, filter);
			const have = new Set(cards.map((c) => c.id));
			const fresh = feed.cards.filter((c) => !have.has(c.id));
			const endBounds = endPanel?.getBoundingClientRect();
			const reveal = !quiet || !!(endBounds && endBounds.top < window.innerHeight && endBounds.bottom > 0);
			clearAnswers(fresh.map((c) => c.id));
			cards = [...cards, ...fresh];
			nextCursor = feed.next_cursor;
			sentCursor = feed.cursor ?? feed.next_cursor ?? sentCursor;
			atEnd = nextCursor === null;
			generating = !!feed.generating && !feed.fromCache;
			if (!quiet) checkedEmpty = fresh.length === 0;
			if (fresh.length && reveal) {
				// The end panel moves below the new cards. Scroll anchoring can otherwise keep
				// it on screen, leaving the cards we just fetched above the reader.
				await tick();
				const first = [...document.querySelectorAll<HTMLElement>('.feed [data-card-id]')]
					.find((element) => element.dataset.cardId === fresh[0].id);
				first?.scrollIntoView?.({ behavior: 'instant', block: 'start' });
			}
		} catch (e) {
			// Not "no new cards": the check itself failed.
			if (!quiet) failed(e, (msg) => (checkError = msg));
		} finally {
			checking = false;
		}
	}
</script>

<!-- The page scrolls; the top bar sits above the first card, scrolled away when it loads. -->
<div class="app" style="--chrome-h: {chromeH}px">
<header class="chrome" aria-label="Top bar" bind:offsetHeight={chromeH}>
	<div class="stories-slot"><StoriesRow {stories} onOpen={(i) => (openStory = i)} /></div>
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


<main>
	{#if loading}
		<p class="status">Loading...</p>
	{:else if unpaired}
		<div class="status" role="alert">
			<h2>This device is not paired</h2>
			<p>
				Get a short code, then tell your coding agent the code ("pair code ...") on the computer that runs
				GitTok. You do this once for each device.
			</p>
			<form method="post" action="/pair/code" onsubmit={pairWithCode}>
				<button type="submit" disabled={pairing}>Pair with a code</button>
			</form>
			{#if pairError}<p>{pairError}</p>{/if}
			<button type="button" onclick={load}>Try again</button>
		</div>
	{:else if error}
		<div class="status" role="alert">
			<p class="error">Failed to load feed: {error}</p>
			<button type="button" onclick={load}>Try again</button>
		</div>
	{:else if noRepos}
		<section class="end" aria-label="No repos configured">
			<h2>No repos yet</h2>
			<p>No repos are configured, so there is nothing to make cards from.</p>
			<p>
				On the computer that runs GitTok, ask your coding agent to add one, for example: "add the repo at
				~/src/myapp". Your agent then makes the first cards.
			</p>
			<p class="muted">
				Or in a terminal: <code>gittok repos add &lt;name&gt; &lt;path-or-url&gt;</code>
			</p>
			<button type="button" onclick={load}>Check again</button>
		</section>
	{:else}
		{#if cards.length > 0}
			<Feed {cards} onEvent={onFeedEvent} onNearEnd={loadMore} onActive={rememberCurrent} />
			<GestureHints />
		{/if}
		{#if moreError}
			<section class="end" aria-label="Could not load more cards">
				<p class="error" role="alert">Could not load more cards: {moreError}</p>
				<button type="button" onclick={loadMore}>Try again</button>
			</section>
		{/if}
		{#if atEnd}
			<section class="end" aria-label="End of feed" bind:this={endPanel}>
				<h2>You're all caught up</h2>
				<p>You have seen every card for now.</p>
				{#if generating}
					<p>New cards are being made now. They will appear here.</p>
				{:else}
					<p>
						GitTok makes more cards by itself while a session of your coding agent is open in your
						GitTok directory.
					</p>
					<p>To get more right away, ask the agent there: "make more cards".</p>
				{/if}
				<button type="button" onclick={() => checkAgain()} disabled={checking}>
					{checking ? 'Checking…' : checkError ? 'Try again' : 'Check for new cards'}
				</button>
				{#if checkError}
					<p class="error" role="alert">Could not check for new cards: {checkError}</p>
				{/if}
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
		scroll-snap-align: start;
		display: flex;
		align-items: center;
		border-bottom: 1px solid var(--border);
		padding-top: env(safe-area-inset-top);
		padding-left: env(safe-area-inset-left);
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
		padding: 0 max(16px, env(safe-area-inset-right)) 0 8px;
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
		padding: 0.5rem max(16px, env(safe-area-inset-right)) calc(0.5rem + env(safe-area-inset-bottom))
			max(16px, env(safe-area-inset-left));
		background: var(--surface);
		border-top: 1px solid var(--border);
		color: var(--muted);
		font-size: 0.85rem;
		text-align: center;
	}
	.status {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
		height: calc(100dvh - var(--chrome-h, 0px));
		margin: 0;
		padding: 0 max(16px, env(safe-area-inset-right)) env(safe-area-inset-bottom)
			max(16px, env(safe-area-inset-left));
		text-align: center;
		color: var(--muted);
	}
	.status h2 {
		margin: 0;
		color: var(--text);
	}
	.status p {
		margin: 0;
		max-width: 30rem;
	}
	.end {
		height: 100dvh;
		scroll-snap-align: start;
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 0.75rem;
		padding: env(safe-area-inset-top) max(16px, env(safe-area-inset-right)) env(safe-area-inset-bottom)
			max(16px, env(safe-area-inset-left));
		text-align: center;
	}
	.end h2,
	.end p {
		margin: 0;
	}
	.end code {
		font-size: 0.95em;
	}
	.status button,
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
		color: var(--bad);
	}
</style>
