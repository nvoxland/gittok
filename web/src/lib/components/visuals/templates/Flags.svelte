<script lang="ts">
	import type { FlagsData } from '#lib/types.ts';
	import { shownKeys } from '#lib/beats.ts';
	// `shown`: how many flags the beats player has revealed (all by default).
	let { data, shown = Infinity }: { data: FlagsData; shown?: number } = $props();
	const keys = $derived(shownKeys('flags', data, shown));
</script>

<div class="flags">
	<h3>{data.subject}</h3>
	<div class="cols">
		<div class="col red">
			<h4>Red flags</h4>
			<ul>{#each data.red as f, i (i)}{#if keys.has(`red:${f}`)}<li>{f}</li>{/if}{/each}</ul>
		</div>
		<div class="col green">
			<h4>Green flags</h4>
			<ul>{#each data.green as f, i (i)}{#if keys.has(`green:${f}`)}<li>{f}</li>{/if}{/each}</ul>
		</div>
	</div>
</div>

<style>
	h3 {
		margin: 0 0 0.5rem;
	}
	.cols {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	.col {
		border-radius: 10px;
		padding: 0.6rem;
		min-width: 0;
	}
	.red {
		background: var(--bad-bg);
		border: 1px solid var(--bad);
	}
	.green {
		background: var(--good-bg);
		border: 1px solid var(--good);
	}
	h4 {
		margin: 0 0 0.4rem;
		font-size: 0.8rem;
		text-transform: uppercase;
	}
	.red h4 { color: var(--bad); }
	.green h4 { color: var(--good); }
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		margin-bottom: 0.4rem;
		overflow-wrap: anywhere;
	}
	li {
		animation: plant 0.35s ease-out;
	}
	@keyframes plant {
		from {
			opacity: 0;
			transform: scale(0.6) rotate(-6deg);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		li {
			animation: none;
		}
	}
	.red li::before { content: '\1F6A9  '; }
	.green li::before { content: '\2705  '; }
</style>
