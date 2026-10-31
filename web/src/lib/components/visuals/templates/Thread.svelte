<script lang="ts">
	import type { ThreadData } from '#lib/types.ts';
	// `shown`: how many posts the beats player has revealed (all by default).
	let { data, shown = Infinity }: { data: ThreadData; shown?: number } = $props();
</script>

<ol class="thread">
	{#each data.posts.slice(0, shown) as p, i (i)}
		<li class="post">
			<span class="num">{i + 1}/{data.posts.length}</span>
			<p>{p}</p>
		</li>
	{/each}
</ol>

<style>
	.thread {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.post {
		border-left: 3px solid var(--accent);
		background: var(--surface);
		padding: 0.5rem 0.75rem;
		margin-bottom: 6px;
		border-radius: 0 8px 8px 0;
	}
	.post {
		animation: slide-in 0.35s ease-out;
	}
	@keyframes slide-in {
		from {
			opacity: 0;
			transform: translateX(-14px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.post {
			animation: none;
		}
	}
	.num {
		font-size: 0.75rem;
		color: var(--muted);
		font-weight: 700;
	}
	p {
		margin: 0.15rem 0 0;
		overflow-wrap: anywhere;
	}
</style>
