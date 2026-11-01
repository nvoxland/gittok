<script lang="ts">
	import type { MemeVisual, ResolvedImages } from '#lib/types.ts';
	let { visual, resolved }: { visual: MemeVisual; resolved: ResolvedImages | null } = $props();
</script>

{#if resolved?.images?.length}
	<img
		class="media"
		src={resolved.images[0]}
		width={resolved.width}
		height={resolved.height}
		loading="lazy"
		alt={visual.lines.join(' / ')}
	/>
{:else}
	<p class="missing">Image unavailable</p>
{/if}

<style>
	.media {
		display: block;
		width: 100%;
		height: auto;
		max-height: 38dvh; /* leaves room for a long hook on the card front */
		object-fit: contain;
		border-radius: 8px;
	}
	.missing {
		color: var(--muted);
	}
</style>
