<script lang="ts">
	import Avatar from '#lib/components/Avatar.svelte';
	import type { HotTakeData } from '#lib/types.ts';
	let { data, persona }: { data: HotTakeData; persona?: string } = $props();
</script>

<div class="hot">
	{#if persona}<Avatar handle={persona} size={48} />{/if}
	<blockquote>&ldquo;{data.take}&rdquo;</blockquote>
	{#if persona}<cite>@{persona}</cite>{/if}
</div>

<style>
	.hot {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.6rem;
		text-align: center;
		padding: 1rem 0;
	}
	blockquote {
		margin: 0;
		font-size: 1.7rem;
		font-weight: 800;
		line-height: 1.2;
		overflow-wrap: anywhere;
	}
	cite {
		color: var(--muted);
		font-style: normal;
	}
</style>
