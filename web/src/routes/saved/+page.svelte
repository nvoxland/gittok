<script lang="ts">
	let { data } = $props();
</script>

<a class="back" href="/">&larr; Feed</a>
<h1>Saved</h1>
{#if data.cards.length === 0}
	<p class="empty">Nothing saved yet</p>
{:else}
	<ul class="grid">
		{#each data.cards as card (card.id)}
			<li>
				<a class="tile" href="/card/{encodeURIComponent(card.id)}">
					<span class="meta">{card.repo} · {card.format}</span>
					<span class="hook">{card.hook}</span>
				</a>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.back {
		display: block;
		padding: 0.5rem 16px 0;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
	h1 {
		margin: 0.5rem 16px;
		font-size: 1.25rem;
	}
	.empty {
		margin: 1rem 16px;
		color: var(--muted);
	}
	.grid {
		list-style: none;
		margin: 0;
		padding: 0 16px 16px;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: 0.75rem;
	}
	.tile {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		min-height: 44px;
		height: 100%;
		padding: 0.75rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--surface);
		color: inherit;
		text-decoration: none;
	}
	.meta {
		font-size: 0.75rem;
		color: var(--muted);
	}
	.hook {
		font-weight: 600;
		overflow-wrap: anywhere;
	}
</style>
