<script lang="ts">
	import { imageLoading } from '#lib/imageLoading.ts';
	import type { IllustrationVisual, ResolvedImages } from '#lib/types.ts';
	let { visual, resolved }: { visual: IllustrationVisual; resolved: ResolvedImages | null } =
		$props();
	const loading = imageLoading();
</script>

{#if resolved?.images?.length}
	<figure>
		<img
			src={resolved.images[0]}
			width={resolved.width}
			height={resolved.height}
			{loading}
			decoding="async"
			alt={visual.caption}
		/>
		<figcaption class="caption">{visual.caption}</figcaption>
	</figure>
{:else}
	<p class="missing">Image unavailable</p>
{/if}

<style>
	figure {
		position: relative;
		margin: 0;
	}
	img {
		display: block;
		width: 100%;
		height: auto;
		/* Small enough that a long hook still fits below it: the card front clips, never scrolls,
		   so a taller image lost its bottom and its caption. Contain shows the whole picture. */
		max-height: 38dvh;
		object-fit: contain;
		background: var(--surface);
		border-radius: 8px;
	}
	.caption {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		padding: 1.5rem 0.75rem 0.6rem;
		border-radius: 0 0 8px 8px;
		color: #fff;
		font-weight: 700;
		text-align: center;
		text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
		background: linear-gradient(to top, rgba(0, 0, 0, 0.7), transparent);
	}
	.missing {
		color: var(--muted);
	}
</style>
