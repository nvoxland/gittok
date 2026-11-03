<script lang="ts">
	import { isShrunk } from '#lib/lightbox.ts';
	let {
		code,
		language,
		startLine = 1,
		highlight = [],
		wrap = false,
		fit = false,
		large = false,
		onShrunk
	}: {
		code: string;
		language?: string;
		startLine?: number;
		highlight?: number[];
		wrap?: boolean;
		/** Card front: shrink the font so the longest line fits the width; wrap only past MAX_FIT_COLS. */
		fit?: boolean;
		/** Lightbox: a bigger font, one line per row, scrolls sideways. */
		large?: boolean;
		/** With `fit`: called with whether the fitted font is too small to read. */
		onShrunk?: (shrunk: boolean) => void;
	} = $props();


	// Above this many columns the shrunk font would be too small to read, so lines wrap instead.
	const MAX_FIT_COLS = 64;

	const lines = $derived(code.replace(/\n$/, '').split('\n'));
	// Columns the widest line needs: its text (tabs as 4) plus the line-number gutter and margin.
	const cols = $derived(
		Math.max(...lines.map((l) => l.replace(/\t/g, '    ').length)) +
			String(startLine + lines.length - 1).length +
			2
	);
	const folds = $derived(wrap || (fit && cols > MAX_FIT_COLS));

	let html = $state<string | null>(null);
	let box: HTMLElement | undefined = $state();

	$effect(() => {
		if (!fit || !box || !onShrunk || typeof ResizeObserver === 'undefined') return;
		const el = box;
		const measure = () => onShrunk(folds || isShrunk(el.clientWidth, cols));
		measure();
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		return () => ro.disconnect();
	});

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

<div class:fit-box={fit} bind:this={box}>
	{#if html}
		<div class="codeblock shiki-wrap" class:wrap={folds} class:fit class:large style:--cols={fit ? cols : null}>
			{@html html}
		</div>
	{:else}
		<pre class="codeblock" class:wrap={folds} class:fit class:large style:--cols={fit ? cols : null}><code
				>{#each lines as line, i (i)}<span class="line" class:hl={highlight.includes(startLine + i)}
						><span class="ln">{startLine + i}</span><span class="src">{line}</span></span
					>{/each}</code
			></pre>
	{/if}
</div>

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
		/* Shiki puts a newline between its block-level .line spans; under pre each one became a
		   blank row. Lines keep white-space: pre themselves. */
		white-space: normal;
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
	/* fit: the font shrinks until the widest line (--cols characters) fills the box width,
	   between 0.55rem and 0.8rem, so code on the card front neither scrolls nor wraps. */
	.fit-box {
		container-type: inline-size;
	}
	.codeblock.large {
		font-size: 0.9rem;
	}
	.codeblock.fit {
		overflow-x: hidden;
		font-size: max(0.55rem, min(0.8rem, calc(100cqw / (var(--cols) * 0.62))));
	}
	/* wrap: long lines fold instead of scrolling sideways (used on the card front). */
	.codeblock.wrap {
		overflow-x: hidden;
	}
	.wrap code,
	.wrap :global(pre) {
		width: auto;
	}
	.wrap :global(.line) {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		/* Hanging indent: a wrapped part starts under the code, not under the line number
		   (.ln is 3ch + 1ch margin + 0.5rem padding). */
		padding-left: calc(4ch + 0.5rem);
		text-indent: calc(-4ch - 0.5rem);
	}
	.wrap :global(.ln) {
		text-indent: 0;
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
