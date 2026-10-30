<script lang="ts">
	let { repo, path, commit }: { repo: string; path: string; commit: string } = $props();
</script>

<p class="source">{repo} · {path} · {commit.slice(0, 7)}</p>

<style>
	.source {
		margin: 0 0 0.4rem;
		font-size: 0.75rem;
		color: var(--muted);
		word-break: break-all;
	}
</style>
