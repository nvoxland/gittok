<script lang="ts">
	import { postFollow } from '#lib/api.ts';
	let { data } = $props();
	const p = $derived(data.profile);
	let followed = $state<boolean | undefined>();
	const on = $derived(followed ?? p.followed);

	async function toggle() {
		followed = await postFollow(p.repo, p.path, !on);
	}
</script>

<main class="profile">
	<a class="back" href="/repo/{encodeURIComponent(p.repo)}">&larr; {p.repo}</a>
	<header>
		<div>
			<h1 class="path">{p.path}</h1>
			<span class="repo">{p.repo}</span>
		</div>
		<button type="button" aria-pressed={on} onclick={toggle}>{on ? 'Following' : 'Follow'}</button>
	</header>

	{#if p.history}
		<dl class="stats">
			<div><dt>Commits</dt><dd>{p.history.commits}</dd></div>
			<div><dt>Last touched</dt><dd>{p.history.last_touched ?? 'n/a'}</dd></div>
		</dl>
		{#if p.history.authors.length}
			<p class="authors">
				Top authors:
				{#each p.history.authors as a, i (a.name)}{i ? ', ' : ' '}{a.name} ({a.commits}){/each}
			</p>
		{/if}
	{/if}

	<h2>Cards about this</h2>
	{#if p.cards.length === 0}
		<p class="empty">No cards yet</p>
	{:else}
		<ul class="grid">
			{#each p.cards as c (c.id)}
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
		padding: calc(0.75rem + var(--safe-top)) max(16px, var(--safe-right)) calc(2rem + var(--safe-bottom)) max(16px, var(--safe-left));
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
		justify-content: space-between;
		margin: 0.75rem 0;
	}
	h1 {
		margin: 0;
		font-size: 1.3rem;
		overflow-wrap: anywhere;
	}
	.repo,
	.empty,
	.authors {
		color: var(--muted);
	}
	header button {
		flex: none;
		padding: 0.4rem 0.9rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	header button[aria-pressed='true'] {
		color: var(--accent);
		border-color: var(--accent);
	}
	h2 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--muted);
		margin: 1.25rem 0 0.4rem;
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 8px;
		margin: 0;
	}
	.stats div {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 10px;
		padding: 0.5rem;
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
</style>
