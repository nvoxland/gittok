<script lang="ts">
	import CodeBlock from '../CodeBlock.svelte';
	import SourceLine from '../panels/SourceLine.svelte';
	import type { CodeVisual, ResolvedCode } from '#lib/types.ts';

	let { visual, resolved }: { visual: CodeVisual; resolved: ResolvedCode | null } = $props();
	const callouts = $derived(visual.callouts ?? []);
</script>

<div class="code-visual">
	<SourceLine repo={visual.repo} path={visual.path} commit={visual.commit} />
	{#if resolved}
		<CodeBlock
			code={resolved.code}
			language={resolved.language}
			startLine={resolved.start_line}
			highlight={callouts.map((c) => c.line)}
			fit
		/>
	{:else}
		<p class="missing">Code unavailable</p>
	{/if}
	{#if callouts.length}
		<ul class="callouts">
			{#each callouts as c (c.line)}
				<li><span class="at">L{c.line}</span> {c.text}</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.callouts {
		list-style: none;
		margin: 0.5rem 0 0;
		padding: 0;
		font-size: 0.85rem;
	}
	.at {
		color: var(--accent);
		font-weight: 600;
	}
	.missing {
		color: var(--muted);
	}
</style>
