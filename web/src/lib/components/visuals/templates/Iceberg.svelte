<script lang="ts">
	import type { IcebergData } from '#lib/types.ts';
	// `shown`: how many layers the beats player has revealed (all by default).
	let { data, shown = Infinity }: { data: IcebergData; shown?: number } = $props();
	const n = $derived(Math.max(1, data.layers.length - 1));
</script>

<div class="iceberg">
	<h3>{data.title}</h3>
	{#each data.layers.slice(0, shown) as layer, i (i)}
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
	.layer {
		animation: sink 0.45s ease-out;
	}
	/* each new layer rises out of the deep, so the eye moves down the iceberg */
	@keyframes sink {
		from {
			opacity: 0;
			transform: translateY(18px) scale(0.98);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.layer {
			animation: none;
		}
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
