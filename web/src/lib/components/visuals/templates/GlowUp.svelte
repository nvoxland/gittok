<script lang="ts">
	import type { GlowUpData } from '#lib/types.ts';
	let { data }: { data: GlowUpData } = $props();
</script>

<div class="glow">
	<h3>{data.subject}</h3>
	<div class="split">
		<div class="side before">
			<h4>{data.before.label}</h4>
			<p>{data.before.text}</p>
		</div>
		<div class="side after">
			<h4>{data.after.label}</h4>
			<p>{data.after.text}</p>
		</div>
	</div>
</div>

<style>
	h3 {
		margin: 0 0 0.5rem;
	}
	.split {
		display: grid;
		grid-template-columns: 1fr 1fr;
		border-radius: 12px;
		overflow: hidden;
		border: 1px solid var(--border);
	}
	.side {
		padding: 0.8rem;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.before {
		background: var(--bad-bg);
		filter: grayscale(0.4);
	}
	.after {
		background: var(--good-bg);
	}
	h4 {
		margin: 0 0 0.4rem;
		text-transform: uppercase;
		font-size: 0.75rem;
		color: var(--muted);
	}
	p {
		margin: 0;
	}
</style>
