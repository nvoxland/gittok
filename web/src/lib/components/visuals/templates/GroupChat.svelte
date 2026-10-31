<script lang="ts">
	import Poster from '#lib/components/Poster.svelte';
	import { accountHandle } from '#lib/account.ts';
	import type { GroupChatData } from '#lib/types.ts';
	// `shown`: how many messages the beats player has revealed (all by default).
	let { data, shown = Infinity }: { data: GroupChatData; shown?: number } = $props();
	const senders = $derived([...new Set(data.messages.map((m) => m.from))]);
	const next = $derived(shown < data.messages.length ? data.messages[shown] : null);
</script>

<div class="chat">
	<h3>{data.title}</h3>
	<div class="messages">
		{#each data.messages.slice(0, shown) as m, i (i)}
			<div class="bubble" class:alt={senders.indexOf(m.from) % 2 === 1}>
				<div class="from"><Poster account={m.from} size={18} /></div>
				<p aria-label="{accountHandle(m.from)} says">{m.text}</p>
			</div>
		{/each}
		{#if next && shown > 0}
			<div class="bubble typing" class:alt={senders.indexOf(next.from) % 2 === 1} aria-hidden="true">
				<span></span><span></span><span></span>
			</div>
		{/if}
	</div>
</div>

<style>
	h3 {
		margin: 0 0 0.5rem;
		text-align: center;
		font-size: 1rem;
	}
	.messages {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.bubble {
		max-width: 85%;
		align-self: flex-start;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 14px 14px 14px 4px;
		padding: 0.4rem 0.7rem;
	}
	.bubble {
		animation: pop 0.25s ease-out;
		transform-origin: bottom left;
	}
	.bubble.alt {
		transform-origin: bottom right;
	}
	@keyframes pop {
		from {
			opacity: 0;
			transform: scale(0.85) translateY(6px);
		}
	}
	.typing {
		display: flex;
		gap: 4px;
		padding: 0.6rem 0.8rem;
	}
	.typing span {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: currentColor;
		opacity: 0.4;
		animation: dot 1s infinite;
	}
	.typing span:nth-child(2) {
		animation-delay: 0.15s;
	}
	.typing span:nth-child(3) {
		animation-delay: 0.3s;
	}
	@keyframes dot {
		30% {
			opacity: 1;
			transform: translateY(-3px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.bubble,
		.typing span {
			animation: none;
		}
	}
	.bubble.alt {
		align-self: flex-end;
		background: var(--accent);
		color: var(--bg);
		border-color: transparent;
		border-radius: 14px 14px 4px 14px;
	}
	.from {
		font-size: 0.75rem;
		opacity: 0.8;
	}
	p {
		margin: 0.1rem 0 0;
		overflow-wrap: anywhere;
	}
</style>
