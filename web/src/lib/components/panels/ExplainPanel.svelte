<script lang="ts">
	import { parseMarkdown, type Inline } from '#lib/miniMarkdown.ts';
	import type { CardLink } from '#lib/types.ts';

	let { text, sources = [] }: { text: string; sources?: CardLink[] } = $props();
	const blocks = $derived(parseMarkdown(text));
	const linked = $derived(sources.filter((s) => s.url));
</script>

{#snippet inline(parts: Inline[])}
	{#each parts as part, i (i)}
		{#if part.kind === 'code'}<code>{part.text}</code
			>{:else if part.kind === 'bold'}<strong>{part.text}</strong>{:else}{part.text}{/if}
	{/each}
{/snippet}

<div class="explain">
	{#each blocks as b, i (i)}
		{#if b.type === 'p'}
			<p>{@render inline(b.inline)}</p>
		{:else}
			<ul>
				{#each b.items as item, j (j)}
					<li>{@render inline(item)}</li>
				{/each}
			</ul>
		{/if}
	{/each}
	{#if linked.length > 0}
		<div class="sources">
			<h3>Sources</h3>
			<ul>
				{#each linked as s, i (i)}
					<li>
						<a href={s.url} target="_blank" rel="noopener noreferrer">{s.label}</a>
					</li>
				{/each}
			</ul>
		</div>
	{/if}
</div>

<style>
	.explain {
		font-size: 1.05rem;
		line-height: 1.6;
	}
	p {
		margin: 0 0 1em;
	}
	ul {
		margin: 0 0 1em;
		padding-left: 1.25rem;
	}
	li {
		margin: 0 0 0.4em;
	}
	code {
		font: 0.9em ui-monospace, SFMono-Regular, Menlo, monospace;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 0.05em 0.35em;
		overflow-wrap: anywhere;
	}
	strong {
		color: var(--accent);
	}
	.sources {
		margin-top: 1.5rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--border);
		font-size: 0.8rem;
		color: var(--muted);
	}
	.sources h3 {
		margin: 0 0 0.4rem;
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.sources ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem 0.9rem;
	}
	.sources li {
		margin: 0;
	}
	.sources a {
		color: var(--accent);
		display: inline-block;
		padding: 0.3rem 0;
		overflow-wrap: anywhere;
	}
</style>
