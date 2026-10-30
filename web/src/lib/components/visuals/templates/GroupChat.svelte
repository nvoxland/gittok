<script lang="ts">
	import Poster from '#lib/components/Poster.svelte';
	import { accountHandle } from '#lib/account.ts';
	import type { GroupChatData } from '#lib/types.ts';
	let { data }: { data: GroupChatData } = $props();
	const senders = $derived([...new Set(data.messages.map((m) => m.from))]);
</script>

<div class="chat">
	<h3>{data.title}</h3>
	<div class="messages">
		{#each data.messages as m, i (i)}
			<div class="bubble" class:alt={senders.indexOf(m.from) % 2 === 1}>
				<div class="from"><Poster account={m.from} size={18} /></div>
				<p aria-label="{accountHandle(m.from)} says">{m.text}</p>
			</div>
		{/each}
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
