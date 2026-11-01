<script lang="ts">
	import type { RepoProfile } from '#lib/types.ts';

	let { profile }: { profile: RepoProfile } = $props();
	const s = $derived(profile.stats);
	const last = $derived.by(() => {
		if (!s.last_commit_ts) return 'n/a';
		const ms = s.last_commit_ts > 1e12 ? s.last_commit_ts : s.last_commit_ts * 1000;
		return new Date(ms).toISOString().slice(0, 10);
	});
</script>

<main class="profile">
	<a class="back" href="/">&larr; Feed</a>
	<header>
		{#if profile.mascot_image}
			<img class="mascot" src={profile.mascot_image} alt={profile.mascot ?? 'mascot'} width="72" height="72" />
		{:else}
			<div class="mascot placeholder" aria-hidden="true">{profile.name.slice(0, 1).toUpperCase()}</div>
		{/if}
		<div>
			<h1>{profile.name}</h1>
			{#if profile.group}<span class="group">{profile.group}</span>{/if}
			<a class="group" href="/repo/{encodeURIComponent(profile.name)}/map">Map</a>
		</div>
	</header>

	<dl class="stats">
		<div><dt>Commits (365d)</dt><dd>{s.commits_365}</dd></div>
		<div><dt>Authors</dt><dd>{s.authors_365}</dd></div>
		<div><dt>Last commit</dt><dd>{last}</dd></div>
	</dl>

	<div class="lists">
		<section>
			<h2>Top files</h2>
			<ul>
				{#each s.top_files as f (f.path)}
					<li><span class="path">{f.path}</span><span class="n">{f.commits}</span></li>
				{/each}
			</ul>
		</section>
		<section>
			<h2>Top dirs</h2>
			<ul>
				{#each s.top_dirs as f (f.path)}
					<li>
						<a
							class="path"
							href="/?{new URLSearchParams({ repo: profile.name, dir: f.path }).toString()}"
							>{f.path}</a
						><span class="n">{f.commits}</span>
					</li>
				{/each}
			</ul>
		</section>
	</div>

	{#if profile.verdicts?.length}
		<h2>Verdicts</h2>
		<ul class="verdicts">
			{#each profile.verdicts as v (v.dir)}
				<li data-testid="verdicts-{v.dir}">
					<span class="path">{v.dir}</span>
					{#each Object.entries(v.counts) as [verdict, n] (verdict)}
						<span class="chip {verdict}">{verdict} {n}</span>
					{/each}
				</li>
			{/each}
		</ul>
	{/if}

	<h2>Cards</h2>
	{#if profile.cards.length === 0}
		<p class="empty">No cards yet</p>
	{:else}
		<ul class="grid">
			{#each profile.cards as c (c.id)}
				<li>
					<a href="/card/{encodeURIComponent(c.id)}">
						<span class="fmt">{c.format.replace(/_/g, ' ')}</span>
						<span class="hook">{c.hook}</span>
						<span class="by">@{c.persona}</span>
					</a>
				</li>
			{/each}
		</ul>
	{/if}
</main>

<style>
	.profile {
		padding: 0.75rem 16px 2rem;
		max-width: 48rem;
		margin: 0 auto;
	}
	.back {
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
	header {
		display: flex;
		gap: 1rem;
		align-items: center;
		margin: 0.75rem 0;
	}
	.mascot {
		width: 72px;
		height: 72px;
		border-radius: 16px;
		object-fit: cover;
		flex: none;
	}
	.placeholder {
		display: grid;
		place-items: center;
		background: var(--border);
		font-size: 2rem;
		font-weight: 800;
		color: var(--muted);
	}
	h1 {
		margin: 0;
		font-size: 1.6rem;
		overflow-wrap: anywhere;
	}
	h2 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--muted);
		margin: 1.25rem 0 0.4rem;
	}
	.group {
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.05rem 0.6rem;
		font-size: 0.8rem;
		color: var(--muted);
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
		margin: 0;
	}
	.stats div {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 10px;
		padding: 0.5rem;
		min-width: 0;
	}
	dt {
		font-size: 0.7rem;
		color: var(--muted);
	}
	dd {
		margin: 0;
		font-weight: 700;
		font-size: 1.1rem;
	}
	.lists {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
		gap: 0 16px;
	}
	.lists ul {
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: 0.85rem;
	}
	.lists li {
		display: flex;
		justify-content: space-between;
		gap: 0.5rem;
		padding: 0.2rem 0;
		border-bottom: 1px solid var(--border);
	}
	.path {
		overflow-wrap: anywhere;
		min-width: 0;
	}
	.n {
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.verdicts {
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: 0.85rem;
	}
	.verdicts li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		padding: 0.25rem 0;
		border-bottom: 1px solid var(--border);
	}
	.verdicts .path {
		flex: 1 1 8rem;
	}
	.chip {
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.05rem 0.6rem;
		font-size: 0.75rem;
		color: var(--muted);
	}
	.grid {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
		gap: 8px;
	}
	.grid a {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		height: 100%;
		padding: 0.6rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 10px;
		color: inherit;
		text-decoration: none;
	}
	.fmt {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--accent);
	}
	.hook {
		font-size: 0.9rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.by {
		margin-top: auto;
		font-size: 0.75rem;
		color: var(--muted);
	}
	.empty {
		color: var(--muted);
	}
</style>
