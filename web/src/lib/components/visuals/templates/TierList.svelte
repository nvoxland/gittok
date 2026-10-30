<script lang="ts">
	import type { TierListData } from '#lib/types.ts';
	let { data }: { data: TierListData } = $props();
</script>

<div class="tiers">
	<h3>{data.title}</h3>
	{#each data.rows as row, i (i)}
		<div class="row">
			<div class="tier" data-tier={row.tier}>{row.tier}</div>
			<ul>
				{#each row.items as it, j (j)}
					<li><strong>{it.name}</strong> <span class="why">{it.why}</span></li>
				{/each}
			</ul>
		</div>
	{/each}
</div>

<style>
	h3 {
		margin: 0 0 0.5rem;
	}
	.row {
		display: flex;
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
		margin-bottom: 4px;
		background: var(--surface);
	}
	.tier {
		flex: none;
		width: 3rem;
		display: grid;
		place-items: center;
		font-weight: 800;
		font-size: 1.4rem;
		color: #111;
	}
	[data-tier='S'] { background: #ff7f7f; }
	[data-tier='A'] { background: #ffbf7f; }
	[data-tier='B'] { background: #ffdf7f; }
	[data-tier='C'] { background: #ffff7f; }
	[data-tier='D'] { background: #bfff7f; }
	[data-tier='F'] { background: #7fbfff; }
	ul {
		list-style: none;
		margin: 0;
		padding: 0.5rem 0.75rem;
		flex: 1;
		min-width: 0;
	}
	li {
		margin: 0.15rem 0;
		overflow-wrap: anywhere;
	}
	.why {
		color: var(--muted);
		font-size: 0.85rem;
	}
</style>
