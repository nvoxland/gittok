<script lang="ts">
	let {
		code,
		language,
		startLine = 1,
		highlight = []
	}: { code: string; language?: string; startLine?: number; highlight?: number[] } = $props();

	const lines = $derived(code.replace(/\n$/, '').split('\n'));

	let html = $state<string | null>(null);

	$effect(() => {
		const src = code.replace(/\n$/, '');
		const first = startLine;
		const hl = new Set(highlight);
		const lang = language ?? 'text';
		let cancelled = false;
		html = null;
		import('shiki')
			.then(({ codeToHtml }) =>
				codeToHtml(src, {
					lang,
					themes: { light: 'github-light', dark: 'github-dark' },
					defaultColor: false,
					transformers: [
						{
							line(node, n) {
								const num = first + n - 1;
								if (hl.has(num)) this.addClassToHast(node, 'hl');
								node.children.unshift({
									type: 'element',
									tagName: 'span',
									properties: { class: 'ln' },
									children: [{ type: 'text', value: String(num) }]
								});
							}
						}
					]
				})
			)
			.then((out) => {
				if (!cancelled && typeof out === 'string') html = out;
			})
			.catch(() => {
				// Plain text fallback stays in place.
			});
		return () => {
			cancelled = true;
		};
	});
</script>

{#if html}
	<div class="codeblock shiki-wrap">{@html html}</div>
{:else}
<pre class="codeblock"><code
		>{#each lines as line, i (i)}<span class="line" class:hl={highlight.includes(startLine + i)}
				><span class="ln">{startLine + i}</span><span class="src">{line}</span></span
			>{/each}</code
	></pre>
{/if}

<style>
	.codeblock {
		margin: 0;
		overflow-x: auto;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0.5rem 0;
		font: 0.8rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
	}
	code {
		display: block;
		width: max-content;
		min-width: 100%;
	}
	.shiki-wrap :global(pre) {
		margin: 0;
		background: transparent !important;
		width: max-content;
		min-width: 100%;
	}
	.shiki-wrap :global(code) {
		display: block;
	}
	.shiki-wrap :global(span:not(.ln)) {
		color: var(--shiki-light);
	}
	@media (prefers-color-scheme: dark) {
		.shiki-wrap :global(span:not(.ln)) {
			color: var(--shiki-dark);
		}
	}
	.codeblock :global(.line) {
		display: block;
		padding-right: 0.75rem;
		white-space: pre;
	}
	.codeblock :global(.line.hl) {
		background: color-mix(in srgb, var(--accent) 18%, transparent);
	}
	.codeblock :global(.ln) {
		display: inline-block;
		min-width: 3ch;
		margin-right: 1ch;
		padding-left: 0.5rem;
		text-align: right;
		color: var(--muted);
		user-select: none;
	}
</style>
