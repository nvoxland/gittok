<script lang="ts">
	// Test harness: renders Beats with a child that prints `shown`.
	import Beats from '../Beats.svelte';
	let props: Omit<import('svelte').ComponentProps<typeof Beats>, 'children'> = $props();
</script>

<Beats {...props}>
	{#snippet children(shown: number)}<p data-testid="shown">{shown}</p>{/snippet}
</Beats>
