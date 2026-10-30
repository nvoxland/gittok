<script lang="ts">
	import type { ThreadData } from '#lib/types.ts';
	let { data }: { data: ThreadData } = $props();
</script>

<ol class="thread">
	{#each data.posts as p, i (i)}
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
