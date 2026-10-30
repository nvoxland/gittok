<script lang="ts">
	import type { TextVisual } from '#lib/types.ts';

	let { visual }: { visual: TextVisual } = $props();
</script>

<div class="text-visual">
	{#if visual.title}<h3>{visual.title}</h3>{/if}
	{#if visual.body}<p>{visual.body}</p>{/if}
	{#if visual.bullets?.length}
		<ul>
			{#each visual.bullets as b, i (i)}<li>{b}</li>{/each}
		</ul>
	{/if}
</div>

<style>
	h3 {
		margin: 0 0 0.5rem;
	}
	p {
		margin: 0 0 0.5rem;
		line-height: 1.5;
	}
	ul {
		margin: 0;
		padding-left: 1.25rem;
	}
</style>
