<script lang="ts">
	import type { ComicVisual, ResolvedImages } from '#lib/types.ts';
	let { visual, resolved }: { visual: ComicVisual; resolved: ResolvedImages | null } = $props();
	const cols = $derived(visual.panels.length % 2 === 0 ? 2 : 1);
</script>

<div class="grid cols-{cols}">
	{#each visual.panels as p, i (i)}
		<figure class="panel">
			{#if resolved?.images?.[i]}
				<img
					src={resolved.images[i]}
					width={resolved.width}
					height={resolved.height}
					loading="lazy"
					alt={p.caption}
				/>
			{/if}
			<figcaption>{p.caption}</figcaption>
		</figure>
	{/each}
</div>

<style>
	.grid {
		display: grid;
		gap: 6px;
	}
	.cols-2 {
		grid-template-columns: 1fr 1fr;
	}
	.cols-1 {
		grid-template-columns: 1fr;
	}
	.panel {
		position: relative;
		margin: 0;
		border: 2px solid var(--text);
		border-radius: 4px;
		overflow: hidden;
		background: var(--surface);
		min-height: 3rem;
	}
	img {
		display: block;
		width: 100%;
		height: auto;
	}
	figcaption {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		padding: 0.3rem 0.4rem;
		font-size: 0.8rem;
		font-weight: 600;
		color: #111;
		background: rgba(255, 255, 255, 0.85);
	}
</style>
