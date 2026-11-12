<script lang="ts">
	import Card from '#lib/components/Card.svelte';
	let { data } = $props();
</script>

<a class="back" href="/">&larr; Feed</a>
<Card card={data.card} />

<style>
	.back {
		display: block;
		padding: calc(0.5rem + var(--safe-top)) max(16px, var(--safe-right)) 0 max(16px, var(--safe-left));
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
</style>
