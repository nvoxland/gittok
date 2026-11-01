<script lang="ts">
	import type { ComicVisual, ResolvedImages } from '#lib/types.ts';
	let {
		visual,
		resolved,
		shown = Infinity
	}: { visual: ComicVisual; resolved: ResolvedImages | null; shown?: number } = $props();
	// While the card plays (beats), one panel at a time fills the width, like a short video.
	// Finished or static: every panel at once, 3 as one strip, 2 or 4 as a 2-wide grid.
	const playing = $derived(Number.isFinite(shown));
	const current = $derived(Math.min(Math.max(shown, 1), visual.panels.length) - 1);
	const items = $derived(
		visual.panels.map((p, i) => ({ p, i })).filter(({ i }) => !playing || i === current)
	);
	const cols = $derived(playing ? 1 : visual.panels.length === 3 ? 3 : 2);
</script>

<div class="grid cols-{cols}">
	{#each items as { p, i } (i)}
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
	.cols-1 {
		grid-template-columns: 1fr;
	}
	.cols-1 img {
		max-height: 38dvh;
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
