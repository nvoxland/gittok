<script lang="ts">
	import Poster from '#lib/components/Poster.svelte';
	import type { DayInLifeData } from '#lib/types.ts';
	let { data }: { data: DayInLifeData } = $props();
</script>

<div class="day">
	<h3>A day in the life of <Poster account={data.subject} size={22} /></h3>
	<ol>
		{#each data.steps as s, i (i)}
			<li class="step">
				<span class="time">{s.time}</span>
				<span class="text">{s.text}</span>
			</li>
		{/each}
	</ol>
</div>

<style>
	h3 {
		margin: 0 0 0.75rem;
		font-size: 1rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		align-items: center;
	}
	ol {
		list-style: none;
		margin: 0;
		padding: 0 0 0 0.5rem;
		border-left: 2px solid var(--border);
	}
	.step {
		position: relative;
		display: flex;
		gap: 0.75rem;
		padding: 0 0 0.9rem 0.9rem;
	}
	.step::before {
		content: '';
		position: absolute;
		left: -0.9rem;
		top: 0.35rem;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--accent);
	}
	.time {
		flex: none;
		font-variant-numeric: tabular-nums;
		font-weight: 700;
		color: var(--accent);
	}
	.text {
		overflow-wrap: anywhere;
	}
</style>
