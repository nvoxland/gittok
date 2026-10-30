<script lang="ts">
	import Card from '#lib/components/Card.svelte';
	let { data } = $props();
</script>

<a class="back" href="/">&larr; Feed</a>
<Card card={data.card} />

<style>
	.back {
		display: block;
		padding: 0.5rem 16px 0;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
</style>
