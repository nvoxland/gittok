<script lang="ts">
	import { onMount } from 'svelte';
	import Feed from '#lib/components/Feed.svelte';
	import StoriesRow from '#lib/components/StoriesRow.svelte';
	import StoryViewer from '#lib/components/StoryViewer.svelte';
	import NotificationBell from '#lib/components/NotificationBell.svelte';
	import { fetchFeed, fetchStories, markStoriesSeen, postEvents } from '#lib/api.ts';
	import { createBatcher } from '#lib/batcher.ts';
	import { clearAnswers } from '#lib/cardState.ts';
	import type { Card, Story } from '#lib/types.ts';

	let cards = $state<Card[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let fromCache = $state(false);
	let stories = $state<Story[]>([]);
	let openStory = $state<number | null>(null);

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
			const feed = await fetchFeed();
			fromCache = !!feed.fromCache;
			const fresh = feed.cards;
			// Cards the server serves again are new or due for review: let them be answered again.
			clearAnswers(fresh.map((c) => c.id));
			cards = fresh;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}
</script>

<div class="app">
<header class="chrome" aria-label="Top bar">
	<div class="stories-slot"><StoriesRow {stories} onOpen={(i) => (openStory = i)} /></div>
	<nav class="links">
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
	{#if error}
		<p class="status error" role="alert">Failed to load feed: {error}</p>
	{:else if loading}
		<p class="status">Loading...</p>
	{:else if cards.length === 0}
		<p class="status">No cards yet</p>
	{:else}
		<Feed {cards} onEvent={(e) => batcher.push(e)} />
	{/if}
</main>
</div>

<style>
	/* The top bar takes its own row, so it never covers a card's header. */
	.app {
		height: 100dvh;
		display: flex;
		flex-direction: column;
	}
	.chrome {
		flex: none;
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
	main {
		flex: 1;
		min-height: 0;
	}
	.links a {
		display: inline-flex;
		align-items: center;
		min-height: 44px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
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
		height: 100%;
		margin: 0;
		color: var(--muted);
	}
	.error {
		color: #e5484d;
	}
</style>
