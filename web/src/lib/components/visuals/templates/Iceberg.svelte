<script lang="ts">
	import type { IcebergData } from '#lib/types.ts';
	let { data }: { data: IcebergData } = $props();
	const n = $derived(Math.max(1, data.layers.length - 1));
</script>

<div class="iceberg">
	<h3>{data.title}</h3>
	{#each data.layers as layer, i (i)}
		<div class="layer" data-depth={i} style="--t:{i / n}">
			<h4>{layer.label}</h4>
			<ul>
				{#each layer.items as item, j (j)}<li>{item}</li>{/each}
			</ul>
		</div>
	{/each}
</div>

<style>
	h3 {
		margin: 0 0 0.5rem;
	}
	.layer {
		padding: 0.75rem 1rem;
		color: #fff;
		background: color-mix(in srgb, #7fc8f8 calc((1 - var(--t)) * 100%), #05182e);
		text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
	}
	.layer:first-of-type {
		border-radius: 12px 12px 0 0;
	}
	.layer:last-child {
		border-radius: 0 0 12px 12px;
	}
	h4 {
		margin: 0 0 0.3rem;
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		opacity: 0.85;
	}
	ul {
		margin: 0;
		padding-left: 1.1rem;
	}
</style>
