<script lang="ts">
	import { parseMarkdown, type Inline } from '#lib/miniMarkdown.ts';
	import type { CardLink, Claim } from '#lib/types.ts';

	let {
		text,
		sources = [],
		learn,
		claims = [],
		claimUrls = [],
		checked = false
	}: {
		text: string;
		sources?: CardLink[];
		learn?: string;
		claims?: Claim[];
		claimUrls?: (string | null)[];
		checked?: boolean;
	} = $props();

	function tag(c: Claim): string {
		const s = c.source;
		if ('commit' in s) return `per commit ${s.commit.slice(0, 7)}`;
		if ('pr' in s) return 'per PR';
		if ('doc' in s) return 'per doc';
		return 'per comment';
	}
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
	{#if learn}
		<p class="learn"><strong>You'll learn:</strong> {learn}</p>
	{/if}
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
	{#if claims.length > 0}
		<ul class="claims">
			{#each claims as c, i (i)}
				<li>
					<span class="claim-text">{c.text}</span>
					{#if claimUrls[i]}
						<a class="claim-tag" href={claimUrls[i]} target="_blank" rel="noopener noreferrer"
							>{tag(c)}</a
						>
					{:else}
						<span class="claim-tag">{tag(c)}</span>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
	{#if checked}
		<p class="checked" title="Facts in this card were checked against the code">✓ checked</p>
	{/if}
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
	.learn {
		padding: 0.5rem 0.75rem;
		border-left: 3px solid var(--accent);
		background: var(--surface);
		border-radius: 4px;
		font-size: 0.95rem;
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
	.claims {
		list-style: none;
		padding: 0;
	}
	.claim-text {
		font-style: italic;
	}
	.claim-tag {
		display: inline-block;
		margin-left: 0.4em;
		padding: 0 0.45em;
		border: 1px solid var(--border);
		border-radius: 999px;
		font-size: 0.7rem;
		color: var(--muted);
		text-decoration: none;
	}
	a.claim-tag {
		color: var(--accent);
	}
	.checked {
		margin: 0 0 1em;
		font-size: 0.75rem;
		color: var(--muted);
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
