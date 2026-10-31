<script lang="ts">
	import type { TierListData } from '#lib/types.ts';
	import { shownKeys } from '#lib/beats.ts';
	// `shown`: how many tiers the beats player has revealed, worst first (all by default).
	let { data, shown = Infinity }: { data: TierListData; shown?: number } = $props();
	const visible = $derived(shownKeys('tier_list', data, shown));
</script>

<div class="tiers">
	<h3>{data.title}</h3>
	{#each data.rows as row, i (i)}
		{#if visible.has(row.tier)}
		<div class="row">
			<div class="tier" data-tier={row.tier}>{row.tier}</div>
			<ul>
				{#each row.items as it, j (j)}
					<li><strong>{it.name}</strong> <span class="why">{it.why}</span></li>
				{/each}
			</ul>
		</div>
		{/if}
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
	.row {
		animation: drop-in 0.35s ease-out;
	}
	.row:has([data-tier='S']) {
		animation: s-reveal 0.6s cubic-bezier(0.2, 1.4, 0.4, 1);
	}
	@keyframes drop-in {
		from {
			opacity: 0;
			transform: translateY(-14px);
		}
	}
	@keyframes s-reveal {
		from {
			opacity: 0;
			transform: scale(0.85);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.row,
		.row:has([data-tier='S']) {
			animation: none;
		}
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
