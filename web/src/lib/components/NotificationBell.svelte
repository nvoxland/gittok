<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchNotifications } from '#lib/api.ts';

	let { intervalMs = 60_000 }: { intervalMs?: number } = $props();
	let unread = $state(0);

	async function refresh() {
		try {
			unread = (await fetchNotifications(true)).unread;
		} catch {
			// keep the last known count
		}
	}

	onMount(() => {
		void refresh();
		const timer = setInterval(() => {
			if (document.visibilityState === 'visible') void refresh();
		}, intervalMs);
		const onVis = () => {
			if (document.visibilityState === 'visible') void refresh();
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			clearInterval(timer);
			document.removeEventListener('visibilitychange', onVis);
		};
	});
</script>

<a class="bell" href="/notifications" aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}>
	<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
		<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
		<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
	</svg>
	{#if unread > 0}
		<span class="badge" data-testid="badge">{unread > 99 ? '99+' : unread}</span>
	{/if}
</a>

<style>
	.bell {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 44px;
		min-height: 44px;
		color: var(--muted);
	}
	.badge {
		position: absolute;
		top: 4px;
		right: 2px;
		min-width: 16px;
		padding: 0 4px;
		border-radius: 8px;
		background: var(--news);
		color: #fff;
		font-size: 0.65rem;
		font-weight: 700;
		line-height: 16px;
		text-align: center;
	}
</style>
