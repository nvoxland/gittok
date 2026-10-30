<script lang="ts">
	import type { ChartVisual, ResolvedChart } from '#lib/types.ts';
	let { visual, resolved }: { visual: ChartVisual; resolved: ResolvedChart | null } = $props();

	const bars = $derived(resolved?.bars ?? []);
	const vertical = $derived(visual.chart === 'commit_hours');
	const title = $derived(resolved?.title || visual.title || '');
	const max = $derived(Math.max(1, ...bars.map((b) => b.value)));
	const short = (l: string) => (l.includes('/') ? l.replace(/\/+$/, '').split('/').pop() || l : l);

	// Horizontal layout in a 360 wide viewBox; vertical likewise.
	const W = 360;
	const rowH = 28;
	const labelW = 130;
	const hHeight = $derived(bars.length * rowH + 40);
	const vHeight = 200;
	const vBarW = $derived(W / Math.max(1, bars.length));
</script>

{#if !resolved || bars.length === 0}
	<p class="empty">No data for this chart.</p>
{:else}
	<figure>
		{#if title}<figcaption class="title">{title}</figcaption>{/if}
		{#if vertical}
			<svg
				class="vertical"
				role="img"
				aria-label={title}
				viewBox="0 0 {W} {vHeight}"
				preserveAspectRatio="xMidYMid meet"
			>
				{#each bars as b, i (i)}
					{@const h = (b.value / max) * (vHeight - 50)}
					<rect
						class="bar"
						x={i * vBarW + 1}
						y={vHeight - 30 - h}
						width={Math.max(1, vBarW - 2)}
						height={h}
						rx="1"
					><title>{b.label}: {b.value}</title></rect>
					{#if i % 3 === 0}
						<text class="tick" x={i * vBarW + vBarW / 2} y={vHeight - 16} text-anchor="middle"
							>{b.label}</text
						>
					{/if}
				{/each}
				<text class="axis" x={W / 2} y={vHeight - 2} text-anchor="middle">{resolved.x_label}</text>
				<text class="axis" x="2" y="10">{resolved.y_label}: max {max}</text>
			</svg>
		{:else}
			<svg
				class="horizontal"
				role="img"
				aria-label={title}
				viewBox="0 0 {W} {hHeight}"
				preserveAspectRatio="xMinYMin meet"
			>
				{#each bars as b, i (i)}
					{@const w = (b.value / max) * (W - labelW - 40)}
					<text class="label" x={labelW - 6} y={i * rowH + 18} text-anchor="end"
						>{short(b.label)}<title>{b.label}</title></text
					>
					<rect class="bar" x={labelW} y={i * rowH + 4} width={Math.max(1, w)} height="18" rx="3"
					><title>{b.label}: {b.value}</title></rect>
					<text class="value" x={labelW + w + 4} y={i * rowH + 18}>{b.value}</text>
				{/each}
				<text class="axis" x={labelW} y={hHeight - 6}>{resolved.x_label}</text>
			</svg>
		{/if}
	</figure>
{/if}

<style>
	figure {
		margin: 0;
	}
	.title {
		font-weight: 700;
		margin-bottom: 0.5rem;
	}
	svg {
		width: 100%;
		height: auto;
		display: block;
	}
	.bar {
		fill: var(--chart-bar, var(--accent));
	}
	text {
		fill: var(--text);
		font-size: 11px;
		font-family: inherit;
	}
	.value,
	.tick,
	.axis {
		fill: var(--muted);
	}
	.empty {
		color: var(--muted);
	}
</style>
