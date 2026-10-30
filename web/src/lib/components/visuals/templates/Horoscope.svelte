<script lang="ts">
	import Poster from '#lib/components/Poster.svelte';
	import type { HoroscopeData } from '#lib/types.ts';
	let { data }: { data: HoroscopeData } = $props();
</script>

<div class="horo">
	<div class="head">
		<span class="star" aria-hidden="true">&#9788;</span>
		<div>
			<div class="sign">{data.sign}</div>
			<Poster account={data.subject} size={20} />
		</div>
	</div>
	<p class="forecast">{data.forecast}</p>
	{#if data.lucky}<p class="lucky">{data.lucky}</p>{/if}
</div>

<style>
	.horo {
		border: 1px solid var(--border);
		border-radius: 16px;
		padding: 1rem;
		background: linear-gradient(160deg, var(--surface), var(--bg));
	}
	.head {
		display: flex;
		gap: 0.75rem;
		align-items: center;
	}
	.star {
		font-size: 2.2rem;
		color: var(--accent);
	}
	.sign {
		font-size: 1.4rem;
		font-weight: 800;
	}
	.forecast {
		line-height: 1.5;
	}
	.lucky {
		color: var(--accent);
		font-weight: 600;
		margin: 0;
	}
</style>
