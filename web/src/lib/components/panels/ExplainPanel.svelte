<script lang="ts">
	let { text }: { text: string } = $props();
	const paragraphs = $derived(text.split(/\n\s*\n/).filter((p) => p.trim() !== ''));
</script>

<div class="explain">
	{#each paragraphs as p, i (i)}
		<p>{p}</p>
	{/each}
</div>

<style>
	p {
		margin: 0 0 1em;
		line-height: 1.5;
	}
</style>
