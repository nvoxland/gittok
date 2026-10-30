<script lang="ts">
	import CodeBlock from '../CodeBlock.svelte';
	import SourceLine from './SourceLine.svelte';
	import type { ResolvedCode } from '#lib/types.ts';

	let {
		repo,
		path,
		commit,
		resolved
	}: { repo: string; path: string; commit: string; resolved: ResolvedCode | null } = $props();
</script>

<div class="code-panel">
	<SourceLine {repo} {path} {commit} />
	{#if resolved}
		<CodeBlock code={resolved.code} language={resolved.language} startLine={resolved.start_line} />
	{:else}
		<p class="missing">Code unavailable</p>
	{/if}
</div>

<style>
	.missing {
		color: var(--muted);
	}
</style>
