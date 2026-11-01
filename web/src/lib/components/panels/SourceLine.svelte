<script lang="ts">
	let {
		repo,
		path,
		commit,
		url,
		onTap
	}: {
		repo: string;
		path: string;
		commit: string;
		url?: string | null;
		onTap?: () => void;
	} = $props();
</script>

<p class="source">
	{#if url}
		<a href={url} target="_blank" rel="noopener noreferrer" onclick={() => onTap?.()}
			>{repo} · {path} · {commit.slice(0, 7)}</a
		>
	{:else}
		<a href="/repo/{encodeURIComponent(repo)}" onclick={() => onTap?.()}
			>{repo} · {path} · {commit.slice(0, 7)}</a
		>
	{/if}
</p>

<style>
	.source a {
		color: inherit;
		display: inline-block;
		padding: 0.6rem 0;
	}
	.source {
		margin: 0 0 0.4rem;
		font-size: 0.75rem;
		color: var(--muted);
		word-break: break-all;
	}
</style>
