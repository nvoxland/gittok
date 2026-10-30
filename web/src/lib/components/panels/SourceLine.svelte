<script lang="ts">
	let {
		repo,
		path,
		commit,
		onTap
	}: { repo: string; path: string; commit: string; onTap?: () => void } = $props();
</script>

<p class="source">
	<a href="/repo/{encodeURIComponent(repo)}" onclick={() => onTap?.()}
		>{repo} · {path} · {commit.slice(0, 7)}</a
	>
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
