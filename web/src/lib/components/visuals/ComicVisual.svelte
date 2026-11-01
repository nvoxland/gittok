<script lang="ts">
	import type { ComicVisual, ResolvedImages } from '#lib/types.ts';
	let { visual, resolved }: { visual: ComicVisual; resolved: ResolvedImages | null } = $props();
	// 3 panels read as one strip; 2 or 4 as a 2-wide grid. Never one tall column: it runs off the front.
	const cols = $derived(visual.panels.length === 3 ? 3 : 2);
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
			<figcaption class="below">{p.caption}</figcaption>
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
	.cols-3 {
		grid-template-columns: 1fr 1fr 1fr;
	}
	.panel {
		position: relative;
		margin: 0;
		border: 2px solid var(--text);
		border-radius: 4px;
		overflow: hidden;
		background: var(--surface);
		display: flex;
		flex-direction: column;
	}
	img {
		display: block;
		width: 100%;
		height: auto;
		max-height: 30dvh;
		object-fit: contain;
		background: #fff;
	}
	figcaption {
		flex: 1;
		padding: 0.3rem 0.4rem;
		font-size: 0.75rem;
		line-height: 1.25;
		font-weight: 600;
		color: #111;
		background: #fff;
		border-top: 2px solid var(--text);
	}
</style>
