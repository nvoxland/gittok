<script lang="ts">
	import { imageLoading } from '#lib/imageLoading.ts';
	import { initials } from '#lib/account.ts';
	let { handle, size = 28 }: { handle: string; size?: number } = $props();
	let failed = $state(false);
	const loading = imageLoading();
</script>

{#if failed}
	<span class="avatar fallback" style="--s:{size}px" aria-hidden="true">{initials(handle)}</span>
{:else}
	<img
		class="avatar"
		style="--s:{size}px"
		src="/api/avatars/{handle}"
		width={size}
		height={size}
		alt=""
		{loading}
		decoding="async"
		onerror={() => (failed = true)}
	/>
{/if}

<style>
	.avatar {
		flex: none;
		width: var(--s);
		height: var(--s);
		border-radius: 50%;
		object-fit: cover;
		background: var(--border);
	}
	.fallback {
		display: inline-grid;
		place-items: center;
		font-size: calc(var(--s) * 0.4);
		font-weight: 700;
		color: var(--text);
	}
</style>
