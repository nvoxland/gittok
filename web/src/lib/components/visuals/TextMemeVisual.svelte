<script lang="ts">
	import type { TextMemeVisual } from '#lib/types.ts';
	// `shown`: how many lines the beats player has revealed (all by default).
	let {
		visual,
		shown = Infinity
	}: { visual: TextMemeVisual; resolved?: unknown; shown?: number } = $props();
	const lines = $derived(visual.lines.slice(0, shown));
	const isNobody = (l: string) => /^nobody\s*:?\s*$/i.test(l.trim());
</script>

{#if visual.style === 'pov'}
	<div class="meme pov">
		<span class="tag">POV:</span>
		{#each lines as l, i (i)}<p>{l}</p>{/each}
	</div>
{:else if visual.style === 'nobody_me'}
	<div class="meme nobody_me">
		{#each lines as l, i (i)}
			<p class:muted={isNobody(l) || /:\s*$/.test(l)} class="line">{l}</p>
		{/each}
	</div>
{:else if visual.style === 'starter_pack'}
	<div class="meme starter_pack">
		<div class="title">Starter pack</div>
		<div class="tiles">
			{#each lines as l, i (i)}<div class="tile">{l}</div>{/each}
		</div>
	</div>
{:else if visual.style === 'expectation_reality'}
	<div class="meme expectation_reality">
		<div class="col exp">
			<h4>Expectation</h4>
			<p>{lines[0]}</p>
		</div>
		<div class="col real">
			<h4>Reality</h4>
			{#each lines.slice(1) as l, i (i)}<p>{l}</p>{/each}
		</div>
	</div>
{:else}
	<div class="meme">
		{#each lines as l, i (i)}<p>{l}</p>{/each}
	</div>
{/if}

<style>
	.meme {
		border: 1px solid var(--border);
		border-radius: 12px;
		background: var(--surface);
		padding: 1rem;
		overflow-wrap: anywhere;
	}
	p {
		margin: 0 0 0.5rem;
		font-size: 1.2rem;
		line-height: 1.35;
	}
	p,
	.tile {
		animation: line-in 0.3s ease-out;
	}
	@keyframes line-in {
		from {
			opacity: 0;
			transform: translateY(8px);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		p,
		.tile {
			animation: none;
		}
	}
	.muted {
		color: var(--muted);
	}
	.nobody_me .line {
		font-weight: 600;
	}
	.nobody_me .line.muted {
		font-weight: 400;
		font-style: italic;
	}
	.tag {
		display: inline-block;
		background: var(--accent);
		color: var(--bg);
		font-weight: 800;
		padding: 0.1rem 0.5rem;
		border-radius: 4px;
		margin-bottom: 0.5rem;
	}
	.title {
		text-transform: uppercase;
		letter-spacing: 0.1em;
		font-weight: 800;
		text-align: center;
		margin-bottom: 0.75rem;
	}
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr));
		gap: 8px;
	}
	.tile {
		border: 2px solid var(--text);
		border-radius: 8px;
		padding: 0.75rem 0.5rem;
		text-align: center;
		font-weight: 600;
		min-height: 4rem;
		display: grid;
		place-items: center;
	}
	.expectation_reality {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	.col {
		border-radius: 8px;
		padding: 0.5rem;
	}
	.exp {
		background: var(--good-bg);
	}
	.real {
		background: var(--bad-bg);
	}
	h4 {
		margin: 0 0 0.4rem;
		text-transform: uppercase;
		font-size: 0.75rem;
		letter-spacing: 0.08em;
		color: var(--muted);
	}
</style>
