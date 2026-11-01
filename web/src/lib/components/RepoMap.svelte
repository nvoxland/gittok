<script lang="ts">
	import type { RepoMap } from '#lib/types.ts';

	let { map }: { map: RepoMap } = $props();
	const known = (novelty: number) => Math.round((1 - novelty) * 100);
	const depth = (dir: string) => dir.split('/').length - 1;
	const href = (dir: string) =>
		`/?${new URLSearchParams({ repo: map.name, dir }).toString()}`;
</script>

<main class="map">
	<a class="back" href="/repo/{encodeURIComponent(map.name)}">&larr; {map.name}</a>
	<h1>Map</h1>
	{#if map.dirs.length === 0}
		<p class="empty">No dirs yet</p>
	{:else}
		<ul>
			{#each map.dirs as d (d.dir)}
				<li data-testid="map-{d.dir}" style="--depth: {depth(d.dir)}">
					<a href={href(d.dir)}>
						<span class="path">{d.dir}</span>
						<span class="bar" aria-hidden="true"><i style="width: {known(d.novelty)}%"></i></span>
						<span class="known">{known(d.novelty)}% known</span>
					</a>
					<div class="meta">
						<span>{d.cards_seen} seen</span>
						<span>{d.cards_available} new</span>
						{#if d.quiz_right + d.quiz_wrong > 0}
							<span>quiz {d.quiz_right}/{d.quiz_right + d.quiz_wrong}</span>
						{/if}
						{#each Object.entries(d.verdicts) as [verdict, n] (verdict)}
							<span class="chip {verdict}">{verdict} {n}</span>
						{/each}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</main>

<style>
	.map {
		padding: 0.75rem 16px 2rem;
		max-width: 48rem;
		margin: 0 auto;
	}
	.back {
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
	h1 {
		margin: 0.5rem 0;
		font-size: 1.4rem;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		padding: 0.4rem 0 0.4rem calc(var(--depth) * 1rem);
		border-bottom: 1px solid var(--border);
	}
	li a {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		min-height: 44px;
		color: inherit;
		text-decoration: none;
	}
	.path {
		flex: 1 1 8rem;
		min-width: 0;
		overflow-wrap: anywhere;
		font-weight: 600;
	}
	.bar {
		flex: 0 0 5rem;
		height: 6px;
		border-radius: 3px;
		background: var(--border);
		overflow: hidden;
	}
	.bar i {
		display: block;
		height: 100%;
		background: var(--accent);
	}
	.known {
		flex: none;
		font-size: 0.75rem;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		font-size: 0.75rem;
		color: var(--muted);
	}
	.chip {
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.05rem 0.6rem;
	}
	.empty {
		color: var(--muted);
	}
</style>
