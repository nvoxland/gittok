<script lang="ts">
	import type { BreakingNewsData } from '#lib/types.ts';
	let { data }: { data: BreakingNewsData } = $props();
	// ticker is optional in the card schema
	const ticker = $derived(data.ticker ?? []);
	const text = $derived(ticker.join('   •   '));
</script>

<div class="news">
	<div class="banner">BREAKING</div>
	<div class="body">
		<h3>{data.headline}</h3>
		{#if data.subhead}<p>{data.subhead}</p>{/if}
	</div>
	{#if ticker.length}
		<div class="ticker" aria-label="Ticker">
			<span class="track">{text}   •   {text}</span>
		</div>
	{/if}
</div>

<style>
	.news {
		border-radius: 8px;
		overflow: hidden;
		border: 1px solid var(--border);
		background: var(--surface);
	}
	.banner {
		background: var(--news);
		color: #fff;
		font-weight: 900;
		letter-spacing: 0.15em;
		padding: 0.3rem 0.75rem;
	}
	.body {
		padding: 0.75rem;
	}
	h3 {
		margin: 0;
		font-size: 1.4rem;
	}
	p {
		margin: 0.4rem 0 0;
		color: var(--muted);
	}
	.ticker {
		overflow: hidden;
		white-space: nowrap;
		background: #111;
		color: #fff;
		padding: 0.35rem 0;
		font-size: 0.85rem;
	}
	.track {
		display: inline-block;
		padding-left: 100%;
		animation: scroll 20s linear infinite;
	}
	@keyframes scroll {
		to {
			transform: translateX(-100%);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.ticker {
			white-space: normal;
		}
		.track {
			animation: none;
			padding-left: 0.75rem;
		}
	}
</style>
