<script module lang="ts">
	// One counter for all diagrams: mermaid ids must be unique in the whole page.
	let seq = 0;
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import type { DiagramVisual } from '#lib/types.ts';

	let { visual }: { visual: DiagramVisual; resolved?: unknown } = $props();
	let svg = $state<string | null>(null);
	let failed = $state(false);

	onMount(() => {
		void draw();
	});

	async function draw() {
		const id = `mmd-${Date.now().toString(36)}-${seq++}`;
		try {
			const mermaid = (await import('mermaid')).default;
			const dark =
				typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches;
			mermaid.initialize({
				startOnLoad: false,
				securityLevel: 'strict',
				theme: dark ? 'dark' : 'default'
			});
			svg = (await mermaid.render(id, visual.mermaid)).svg;
		} catch {
			failed = true;
		}
	}
</script>

<figure>
	{#if visual.title}<figcaption>{visual.title}</figcaption>{/if}
	{#if failed}
		<pre class="source">{visual.mermaid}</pre>
	{:else if svg}
		<div class="diagram">{@html svg}</div>
	{:else}
		<p class="loading">Drawing diagram...</p>
	{/if}
</figure>

<style>
	figure {
		margin: 0;
	}
	figcaption {
		font-weight: 700;
		margin-bottom: 0.5rem;
	}
	.diagram {
		overflow-x: auto;
	}
	.diagram :global(svg) {
		max-width: 100%;
		height: auto;
	}
	.source {
		overflow-x: auto;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0.75rem;
		font-size: 0.8rem;
		margin: 0;
	}
	.loading {
		color: var(--muted);
	}
</style>
