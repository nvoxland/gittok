<script lang="ts">
	import Avatar from './Avatar.svelte';
	import { accountHandle, accountHref, isCodeAccount } from '#lib/account.ts';

	let {
		account,
		kind,
		size = 28
	}: { account: string; kind?: 'file' | 'dir'; size?: number } = $props();
	const code = $derived(isCodeAccount(account));
	const iconKind = $derived(kind ?? (account.endsWith('/') ? 'dir' : 'file'));
</script>

<a class="poster" href={accountHref(account)}>
	{#if code}
		<span class="icon" data-icon={iconKind} style="--s:{size}px" aria-hidden="true">
			{iconKind === 'dir' ? '\u{1F4C1}' : '\u{1F4C4}'}
		</span>
	{:else}
		<Avatar handle={account} {size} />
	{/if}
	<span class="handle">{accountHandle(account)}</span>
</a>

<style>
	.poster {
		color: inherit;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		min-width: 0;
	}
	.icon {
		display: inline-grid;
		place-items: center;
		width: var(--s);
		height: var(--s);
		border-radius: 50%;
		background: var(--border);
		font-size: calc(var(--s) * 0.55);
	}
	.poster:hover .handle {
		text-decoration: underline;
	}
	.handle {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
